"""判断時間の境界・強制選択・遅着回答の棄却を仮想時計で検証します。"""
from concurrent.futures import Future
from types import SimpleNamespace

import numpy as np
import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import enable_chatgpt, parser
from master_duel_advisor.llm_fallback import StrategyFallback
from master_duel_advisor.models import Action, GameState, Observation, Phase, Player
from master_duel_advisor.perception import TesseractOCR
from master_duel_advisor.pipeline import Pipeline


class DeferredExecutor:
    def __init__(self):
        self.futures = []

    def submit(self, *args):
        future = Future()
        future.set_running_or_notify_cancel()
        self.futures.append(future)
        return future


def setup(monkeypatch, cooldown=0, max_calls=5):
    ticks = [100.0]
    clock = lambda: ticks[0]
    monkeypatch.setattr("master_duel_advisor.pipeline.time.monotonic", clock)
    fallback = StrategyFallback(lambda *_: None, timeout=10, cooldown=cooldown,
                                max_calls=max_calls, clock=clock)
    fallback.executor.shutdown()
    executor = DeferredExecutor()
    fallback.executor = executor

    def state(frame):
        actions = [Action(type="ACTIVATE", source_region="action.low", confidence=.985,
                          observed_at=frame.captured_at),
                   Action(type="ACTIVATE", source_region="action.high", confidence=.999,
                          observed_at=frame.captured_at)]
        return GameState(sequence=frame.sequence, captured_at=frame.captured_at,
                         visible_actions=actions,
                         phase=Observation(value=Phase.MAIN1, confidence=1, observed_at=frame.captured_at),
                         turn_player=Observation(value=Player.SELF, confidence=1, observed_at=frame.captured_at),
                         prompt=Observation(value="none", confidence=1, observed_at=frame.captured_at))

    perception = SimpleNamespace(process=state, cards=SimpleNamespace(get=lambda _: None),
                                 cache_hits=0, recognized_regions=0)
    pipeline = Pipeline(perception, strategy_fallback=fallback, clock=clock)
    def frame():
        return Frame(np.zeros((10, 10, 3), np.uint8), ticks[0], int(ticks[0]*10))
    return ticks, pipeline, fallback, executor, frame


def test_exactly_ten_seconds_forces_highest_current_candidate(monkeypatch):
    ticks, pipeline, fallback, executor, frame = setup(monkeypatch)
    assert pipeline.process(frame())["planner_source"] == "llm_pending"
    ticks[0] = 109.99
    assert pipeline.process(frame())["recommendation"]["action"] is None
    assert len(executor.futures) == 1
    ticks[0] = 110
    assert pipeline.decision_due
    result = pipeline.process(frame())
    assert result["planner_source"] == "forced_choice"
    assert result["recommendation"]["action"]["source_region"] == "action.high"
    assert result["metrics"]["decision_elapsed_ms"] == 10000
    assert pipeline.decision_started is None
    assert fallback.key is None


def test_late_answer_is_never_accepted_and_workers_do_not_accumulate(monkeypatch):
    ticks, pipeline, fallback, executor, frame = setup(monkeypatch)
    pipeline.process(frame())
    ticks[0] = 110
    pipeline.process(frame())
    ticks[0] += .05
    assert pipeline.process(frame())["planner_source"] == "forced_choice"
    assert len(executor.futures) == 1
    executor.futures[0].set_result(dict(type="ACTIVATE", source_region="action.low",
                                      card_id=None, target=None, confidence=1, reason="遅着"))
    ticks[0] += .05
    result = pipeline.process(frame())
    assert result["planner_source"] == "llm_pending"
    assert result["recommendation"]["action"] is None
    assert len(executor.futures) == 2


@pytest.mark.parametrize("case", ["cooldown", "budget"])
def test_unavailable_llm_forces_choice_without_waiting_thirty_seconds(monkeypatch, case):
    ticks, pipeline, fallback, executor, frame = setup(monkeypatch, cooldown=30)
    if case == "cooldown":
        fallback.last_started = ticks[0]
    else:
        fallback.calls = fallback.max_calls
    result = pipeline.process(frame())
    assert result["planner_source"] == "forced_choice"
    assert result["metrics"]["decision_elapsed_ms"] == 0
    assert not executor.futures


def test_response_just_before_deadline_is_used(monkeypatch):
    ticks, pipeline, fallback, executor, frame = setup(monkeypatch)
    pipeline.process(frame())
    executor.futures[0].set_result(dict(type="ACTIVATE", source_region="action.low", card_id=None,
                                      target=None, confidence=1, reason="期限内の回答"))
    ticks[0] = 109.99
    result = pipeline.process(frame())
    assert result["planner_source"] == "llm_strategy"
    assert result["recommendation"]["action"]["source_region"] == "action.low"


def test_deadline_does_not_force_stale_or_low_confidence_actions(monkeypatch):
    ticks, pipeline, fallback, executor, frame = setup(monkeypatch)
    old_frame = frame()
    state = pipeline.perception.process(old_frame)
    ticks[0] += 2
    assert pipeline._force_choice(state, state.visible_actions).action is None
    current = pipeline.perception.process(frame())
    low = [a.model_copy(update={"confidence": .5}) for a in current.visible_actions]
    assert pipeline._force_choice(current, low).action is None
    assert pipeline._force_choice(current, []).action is None


def test_recognition_time_is_part_of_llm_budget(monkeypatch):
    ticks, pipeline, fallback, executor, frame = setup(monkeypatch)
    perceive = pipeline.perception.process
    def slow_perception(image):
        ticks[0] += 2
        return perceive(image)
    pipeline.perception.process = slow_perception
    pipeline.process(frame())
    assert fallback.started == 102
    assert fallback.deadline == 110


@pytest.mark.parametrize("timeout", ["10.01", "nan", "inf", "0", "-1"])
def test_cli_cannot_extend_decision_timeout(timeout):
    args = parser().parse_args(["run", "--rect=0,0,1280,720", "--calibration", "a",
                                "--database", "b", "--llm-timeout", timeout])
    with pytest.raises(ValueError, match="10秒"):
        enable_chatgpt(SimpleNamespace(), args)


def test_ocr_subprocess_uses_only_remaining_budget(monkeypatch):
    monkeypatch.setattr("master_duel_advisor.perception.time.monotonic", lambda: 100)
    ocr = TesseractOCR("missing")
    ocr.command = "fixture"
    calls = []
    def run(*args, **kwargs):
        calls.append(kwargs["timeout"])
        return SimpleNamespace(stdout=b"")
    monkeypatch.setattr("master_duel_advisor.perception.subprocess.run", run)
    pixels = np.zeros((40, 60), np.uint8)
    ocr._read_rendering(pixels, 8000, deadline=100.25)
    assert calls == [.25]
    with pytest.raises(TimeoutError):
        ocr._read_rendering(pixels, 8000, deadline=100)
    assert calls == [.25]


def test_agent_forces_click_at_deadline_even_on_unchanged_screen(monkeypatch, tmp_path):
    from master_duel_advisor.agent_loop import AgentLoop, LoopLimits
    from master_duel_advisor.regions import Calibration, Rect, Region
    ticks, pipeline, fallback, executor, frame = setup(monkeypatch)
    calibration = Calibration(name="期限試験", aspect_ratio=1, regions={
        "action.low": Region(kind="action", rect=Rect(x=0, y=0, width=.4, height=.4)),
        "action.high": Region(kind="action", rect=Rect(x=.5, y=.5, width=.4, height=.4))})
    clicks = []
    perceive = pipeline.perception.process
    def perception(image):
        state = perceive(image)
        if clicks:
            state = state.model_copy(update={"terminal": Observation(value=True, confidence=1,
                                                                      observed_at=image.captured_at)})
        return state
    pipeline.perception.process = perception
    pipeline.perception.calibration = calibration
    def sleep(seconds):
        ticks[0] += seconds
    capture = SimpleNamespace(read=frame, close=lambda: None)
    loop = AgentLoop(capture, pipeline, calibration,
                     SimpleNamespace(click=lambda x, y: clicks.append((ticks[0], x, y))),
                     SimpleNamespace(stopped=lambda: False), tmp_path, (0, 0, 10, 10),
                     LoopLimits(max_seconds=12), clock=lambda: ticks[0], sleep=sleep)
    result = loop.run()
    assert result["status"] == "duel_ended"
    assert len(clicks) == 1
    assert 110 <= clicks[0][0] <= 110.051
    assert clicks[0][1:] == (7, 7)
    assert len(executor.futures) == 1
