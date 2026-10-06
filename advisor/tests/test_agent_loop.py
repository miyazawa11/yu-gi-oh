import json
import time
from types import SimpleNamespace
import pytest

import numpy as np

from master_duel_advisor.agent_loop import AgentLoop, LoopLimits, Verification
from master_duel_advisor.capture import Frame
from master_duel_advisor.models import Action, ActionType, GameState, Observation, PlayerState
from master_duel_advisor.regions import Calibration, Rect, Region


class Frames:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.closed = False

    def read(self):
        return next(self.frames, None)

    def close(self):
        self.closed = True


class Clicks:
    def __init__(self):
        self.points = []

    def click(self, x, y):
        self.points.append((x, y))


class Stop:
    def stopped(self):
        return False


class StubPipeline:
    def __init__(self, state, action):
        self.state, self.action = state, action
        self.perception = SimpleNamespace(calibration=None, process=self._perceive)

    def _perceive(self, frame):
        current = self.state
        if frame.sequence > 0:
            current = current.model_copy(update={"terminal": Observation[bool](value=True, confidence=1, observed_at=frame.captured_at)})
        return current.model_copy(update={"sequence": frame.sequence, "captured_at": frame.captured_at})

    def process(self, frame, capture_read_ms=0):
        current = self.state
        if frame.sequence > 0:
            current = current.model_copy(update={"terminal": Observation[bool](value=True, confidence=1, observed_at=frame.captured_at)})
        return {"state": current.model_dump(mode="json"), "recommendation": {"action": self.action.model_dump(mode="json"), "confidence": 1, "reason": "test"}}


def setup(tmp_path, confidence=0.99):
    calibration = Calibration(name="loop", regions={"action.confirm": Region(rect=Rect(x=.4,y=.4,width=.2,height=.2), kind="action")})
    now = time.monotonic()
    action = Action(type=ActionType.CONFIRM, confidence=confidence, source_region="action.confirm", observed_at=now)
    state = GameState(sequence=0,captured_at=now,visible_actions=[action])
    image1 = np.zeros((100,200,3),np.uint8)
    image2 = np.full((100,200,3),255,np.uint8)
    frames=Frames([Frame(image1,now,0),Frame(image2,now+0.01,1)])
    pipeline=StubPipeline(state,action)
    pipeline.perception.calibration=calibration
    clicks=Clicks()
    loop=AgentLoop(frames,pipeline,calibration,clicks,Stop(),tmp_path,(-1920,785,-1720,885),
                   LoopLimits(max_seconds=1,max_actions=2,min_confidence=.98,settle_seconds=0,
                              verify_seconds=.1,verify_poll_seconds=.001))
    return loop,clicks,frames


def test_loop_clicks_calibrated_button_verifies_terminal_and_saves_artifacts(tmp_path):
    loop,clicks,frames=setup(tmp_path)
    result=loop.run()
    assert result["status"]=="duel_ended"
    assert clicks.points==[(-1820,835)]
    assert frames.closed
    entries=[json.loads(line) for line in (tmp_path/"actions.jsonl").read_text().splitlines()]
    assert entries[0]["status"]=="duel_ended"
    assert (tmp_path/"screenshots/before-0000.png").exists()
    assert (tmp_path/"screenshots/after-0001.png").exists()


def test_low_confidence_does_not_click(tmp_path):
    loop,clicks,frames=setup(tmp_path,confidence=.8)
    frames.frames=iter([Frame(np.zeros((100,200,3),np.uint8),loop.pipeline.state.captured_at,0)])
    loop.limits=LoopLimits(max_seconds=.01,max_actions=2,min_confidence=.98,settle_seconds=0,
                           verify_seconds=.01,verify_poll_seconds=.001)
    result=loop.run()
    assert clicks.points==[]
    assert result["status"]=="time_limit"
    assert frames.closed


def test_verification_requires_recognized_change_not_only_animation():
    verifier=Verification(LoopLimits())
    action=Action(type=ActionType.CONFIRM,confidence=1,source_region="action.confirm",observed_at=1)
    before=GameState(sequence=0,captured_at=1,visible_actions=[action])
    after=before.model_copy(update={"sequence":1,"captured_at":2})
    assert not verifier.expected(np.zeros((10,10,3),np.uint8),np.full((10,10,3),255,np.uint8),before,after,action)


def test_action_coordinate_includes_negative_monitor_origin(tmp_path):
    loop,_,_=setup(tmp_path)
    assert loop._coordinates(loop.pipeline.action, (100,200,3))==(-1820,835)


def test_verification_does_not_accept_recognition_loss():
    verifier = Verification(LoopLimits())
    action = Action(type=ActionType.CONFIRM, confidence=1, source_region="action.confirm", observed_at=1)
    before = GameState(sequence=0, captured_at=1, visible_actions=[action],
                       self=PlayerState(
                           lp=Observation(value=8000, confidence=1, observed_at=1)))
    after = GameState(sequence=1, captured_at=2)
    assert not verifier.expected(np.zeros((10,10,3),np.uint8),
                                 np.full((10,10,3),255,np.uint8), before, after, action)


def test_stale_candidate_never_clicks(tmp_path):
    loop, clicks, frames = setup(tmp_path)
    first = next(frames.frames)
    frames.frames = iter([Frame(first.pixels, first.captured_at - 10, 0)])
    # 候補とフレームの時刻が一致していても現在時刻から古い画面は不可。
    loop.pipeline.action = loop.pipeline.action.model_copy(update={"observed_at": first.captured_at - 10})
    loop.limits = LoopLimits(max_seconds=.01, verify_poll_seconds=.001, settle_seconds=0)
    result = loop.run()
    assert result["status"] == "time_limit" and not clicks.points


@pytest.mark.parametrize("values", [{"settle_seconds": -1}, {"verify_poll_seconds": 0},
                                   {"max_seconds": float("nan")}, {"verify_seconds": float("inf")}])
def test_invalid_timing_rejected(values):
    with pytest.raises(ValueError):
        LoopLimits(**values)


def test_fast_loop_reports_latency_and_feedback(tmp_path):
    loop, clicks, _ = setup(tmp_path)
    feedback = []
    loop.pipeline.action_issued = lambda a: feedback.append("issued")
    loop.pipeline.action_feedback = feedback.append
    result = loop.run()
    assert feedback == ["issued", "duel_ended"]
    assert len(clicks.points) == 1
    assert result["observation_to_click_ms_p95"] < 1000


def test_settle_rechecks_decision_before_click(tmp_path):
    loop, clicks, frames = setup(tmp_path)
    # 待機後に終了画面へ切り替わった場合は入力しません。
    loop.limits = LoopLimits(max_seconds=1, settle_seconds=.001, verify_poll_seconds=.001)
    result = loop.run()
    assert result["status"] == "duel_ended"
    assert not clicks.points


def test_completed_strategy_wakes_unchanged_frame_before_refresh(tmp_path):
    from concurrent.futures import Future
    loop, clicks, capture = setup(tmp_path)
    first, terminal = list(capture.frames)
    future = Future()
    loop.pipeline.strategy_fallback = SimpleNamespace(future=future)
    calls = []
    original_process = loop.pipeline.process

    def process(frame, capture_read_ms=0):
        calls.append(frame.sequence)
        if len(calls) == 1:
            return {"state": loop.pipeline.state.model_dump(mode="json"),
                    "recommendation": {"confidence": 0, "reason": "判断中"}}
        return original_process(frame, capture_read_ms)

    def frames():
        yield first
        future.set_result(None)
        # 画素も取得時刻も同一で、通常の差分ゲートは通りません。
        yield first
        yield terminal

    capture.frames = iter(frames())
    loop.pipeline.process = process
    result = loop.run()
    assert len(calls) == 2
    assert len(clicks.points) == 1
    assert result["status"] == "duel_ended"


def test_default_loop_uses_fast_timing():
    assert LoopLimits().settle_seconds == 0
    assert LoopLimits().verify_poll_seconds == .05

def test_loop_pre_admitted_no_candidate_retains_failure(tmp_path):
    from master_duel_advisor.telemetry import summarize
    loop, clicks, frames = setup(tmp_path, confidence=.8)
    loop.telemetry.trials=[{"logical_action":"expected_summon","category":"SPECIAL_SUMMON"}]
    loop.limits=LoopLimits(max_seconds=1,max_actions=2,verify_poll_seconds=.001)
    result=loop.run()
    report=summarize([tmp_path/"logical-actions.jsonl"])
    entries=[json.loads(line) for line in (tmp_path/"logical-actions.jsonl").read_text().splitlines()]
    assert not clicks.points and result["logical_actions"]==1
    assert entries[0]["result"]=="interrupted" and entries[0]["steps_count"]==0
    assert entries[0]["capture_start"] is not None
    assert report["samples"]==0  # 模擬モードをliveへ昇格しない。


@pytest.mark.parametrize("typed,confirmed", [(True,False),(True,True),(False,False)])
def test_typed_response_pending_skips_pixel_fallback_only(tmp_path,typed,confirmed):
    loop,_,capture=setup(tmp_path)
    now=loop.pipeline.state.captured_at
    before=Frame(np.zeros((100,200,3),np.uint8),now,0)
    after=Frame(np.full((100,200,3),255,np.uint8),now+.01,1)
    capture.frames=iter([after])
    rule=SimpleNamespace(logical_end=True,logical_response_decline=object() if typed else None)
    loop.pipeline.planner=SimpleNamespace(rule_for=lambda action:rule,expected=lambda action,state:True)
    loop.pipeline.perception.process=lambda frame:GameState(sequence=frame.sequence,captured_at=frame.captured_at)
    loop.current_action=loop.pipeline.action
    loop.telemetry.active={}
    loop.telemetry.goal_confirmed=lambda current,state:confirmed
    loop.limits=LoopLimits(verify_seconds=.02,verify_poll_seconds=.001)
    calls={"changed":0,"expected":0}
    def changed(*args):
        calls["changed"]+=1
        return True
    def expected(*args):
        calls["expected"]+=1
        return False
    loop.verification.changed=changed
    loop.verification.expected=expected
    _,_,result=loop._verify(before,loop.pipeline.state)
    if typed and not confirmed:
        assert result=="unchanged" and calls=={"changed":0,"expected":0}
    elif typed:
        assert result=="changed" and calls=={"changed":1,"expected":0}
    else:
        assert result=="unchanged" and calls=={"changed":0,"expected":1}
