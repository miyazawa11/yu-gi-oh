"""画面状態を与えた連続判断の検証。自動画面認識や実クリックの精度評価ではない。"""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from master_duel_advisor.agent_loop import LoopLimits, Verification
from master_duel_advisor.models import Action, GameState, Observation
from master_duel_advisor.strategy_rules import RulePlanner, load_planner

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("route_builder", ROOT / "scripts/build_colossus_route.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def obs(value, at):
    return Observation(value=value, confidence=1, observed_at=at, source="synthetic_ui_state")


def state(prompt, facts, at=100):
    facts = {**{key: "1" if facts.get(source) == "true" else "0" for key, source in {
        "count.self.hand.10458": "hand.white.present", "count.self.field.10458": "field.white.present",
        "count.self.hand.13907": "hand.hawk.present", "count.self.field.13906": "field.dark.present",
        "count.self.field.13923": "field.colossus.present"}.items()}, **facts}
    return GameState(sequence=int(at), captured_at=at, turn=obs(1, at), turn_player=obs("self", at),
                     phase=obs("MAIN1", at), prompt=obs(prompt, at), animation=obs(False, at),
                     terminal=obs(False, at), facts={k: obs(v, at) for k, v in facts.items()})


def action(rule, at):
    return Action(type=rule.type, source_region=rule.source_region, card_id=rule.card_id,
                  target=rule.target, confidence=1, observed_at=at)


@pytest.mark.parametrize("chains", [False, True])
def test_whole_route_same_planner_and_no_duplicate_effects(chains):
    book = builder.build_route()
    planner = RulePlanner(book)
    at = 100
    completed = []
    for rule in book.rules:
        if not chains and rule.id.endswith("chain_pass"):
            continue
        s = state(rule.prompt, rule.observed_facts, at)
        a = action(rule, at)
        planner.observe(s)
        assert planner.decide(s, [a]).action == a, (rule.id, planner.snapshot())
        planner.issued(a)
        assert planner.decide(s, [a]).action is None
        expected_prompt = rule.expected_prompts[-1] if not chains else rule.expected_prompts[0]
        after = state(expected_prompt, rule.expected_facts, at + 1)
        assert planner.expected(a, after), rule.id
        planner.feedback("changed")
        assert planner.last_completed == rule.id
        completed.append(rule.id)
        at += 2
    assert completed[-1] == "route_colossus_place"
    assert {"unused.space_search", "unused.white_summon", "unused.13906", "unused.13907"} <= planner.inferred_used
    # 最初の画面に戻っても、同じターンの混沌領域をもう一度開かない。
    start = book.rules[0]
    assert planner.decide(state(start.prompt, start.observed_facts, at), [action(start, at)]).action is None


@pytest.mark.parametrize("status", ["changed", "unchanged", "unexpected_state", "input_blocked", "input_error_outcome_unknown"])
def test_no_progress_without_verified_transition(status):
    planner = RulePlanner(builder.build_route())
    first, second = planner.book.rules[:2]
    planner.issued(action(first, 100))
    planner.feedback(status)
    assert planner.last_completed is None
    assert planner.decide(state(second.prompt, second.observed_facts), [action(second, 100)]).action is None


def test_unknown_or_wrong_selection_never_inferred_and_timeout_cannot_bypass():
    from master_duel_advisor.pipeline import Pipeline
    from types import SimpleNamespace
    import time
    planner = RulePlanner(builder.build_route())
    rule = next(r for r in planner.book.rules if r.id == "route_colossus_tribute_confirm")
    planner.last_completed = rule.follows[0]
    at = time.monotonic()
    a = action(rule, at)
    pipeline = Pipeline(SimpleNamespace(cards=SimpleNamespace(get=lambda key: None)), planner=planner)
    for facts in [{}, {"selection.card": "10458", "selection.count": "1"},
                  {"selection.card": "13906", "selection.count": "2"}]:
        s = state(rule.prompt, facts, at)
        assert planner.decide(s, [a]).action is None
        assert pipeline._force_choice(s, [a]).action is None
    valid = state(rule.prompt, rule.observed_facts, at)
    assert pipeline._force_choice(valid, [a]).action == a


def test_result_requires_idle_prompt_and_card_evidence():
    planner = RulePlanner(builder.build_route())
    rule = planner.book.rules[-1]
    a = action(rule, 100)
    planner.issued(a)
    good = state("none", rule.expected_facts, 101)
    assert not planner.expected(a, state("none", {}, 101))
    assert not planner.expected(a, good.model_copy(update={"animation": obs(True, 101)}))
    assert not planner.expected(a, good.model_copy(update={"prompt": obs("none", 100)}))
    assert planner.expected(a, good)
    planner.feedback("changed")
    assert planner.last_completed == rule.id


def test_reset_and_turn_change_clear_ui_progress_but_pause_preserves_usage():
    planner = RulePlanner(builder.build_route())
    planner.observe(state("none", {}))
    planner.last_completed = "route_hawk_place"
    planner.inferred_used.add("unused.13907")
    planner.reset()
    assert planner.last_completed is None
    assert "unused.13907" in planner.inferred_used
    planner.observe(state("none", {}, 101).model_copy(update={"turn": obs(2, 101)}))
    assert not planner.inferred_used


def test_selected_fact_change_can_verify_without_prompt_change():
    rule = builder.build_route().rules[3]
    before = state("card.select", {"selection.count": "0"})
    after = state("card.select", {"selection.count": "1"}, 101)
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    verification = Verification(LoopLimits())
    assert verification.expected(image, image + 255, before, after, action(rule, 100))
    stale = after.model_copy(update={"facts": {"selection.count": obs("1", 100)}})
    assert not verification.expected(image, image + 255, before, stale, action(rule, 100))


@pytest.mark.parametrize("key,prompt", [("maxx", "chain.response"), ("colossus", "extra.summon_select")])
def test_live_blockers_accept_only_registered_prompt(key, prompt):
    planner = load_planner(ROOT / "data/decks/thunder-dragon-review/strategy-book.json")
    rule = next(r for r in planner.book.rules if r.id == key)
    a = action(rule, 100)
    assert planner.decide(state(prompt, {}), [a]).action == a
    assert planner.decide(state("unrelated", {}), [a]).action is None


def test_route_runs_through_real_pipeline_and_agent_loop(tmp_path):
    import json
    import time
    from types import SimpleNamespace
    from master_duel_advisor.agent_loop import AgentLoop
    from master_duel_advisor.capture import Frame
    from master_duel_advisor.pipeline import Pipeline
    from master_duel_advisor.regions import Calibration, Rect, Region

    book = builder.build_route()
    planner = RulePlanner(book)
    layout = Calibration(name="synthetic_route_not_real_screen", regions={
        r.source_region: Region(kind="action", rect=Rect(x=.1, y=.1, width=.1, height=.1)) for r in book.rules})
    clicks = []

    class Capture:
        def read(self):
            return Frame(np.full((90, 160, 3), len(clicks) * 7, dtype=np.uint8), time.monotonic(), len(clicks))
        def close(self):
            pass

    def perceive(frame):
        index = frame.sequence
        current = book.rules[index] if index < len(book.rules) else None
        previous = book.rules[index-1] if index else None
        facts = {**(previous.expected_facts if previous else {}), **(current.observed_facts if current else {})}
        s = state(current.prompt if current else "none", facts, frame.captured_at)
        return s.model_copy(update={"sequence": index, "visible_actions": [action(current, frame.captured_at)] if current else []})

    perception = SimpleNamespace(process=perceive, cards=SimpleNamespace(get=lambda _: None),
                                 calibration=layout, cache_hits=0, recognized_regions=0)
    pipeline = Pipeline(perception, planner=planner)
    loop = AgentLoop(Capture(), pipeline, layout, SimpleNamespace(click=lambda x,y: clicks.append((x,y))),
                     SimpleNamespace(stopped=lambda: False), tmp_path, (0,0,160,90),
                     LoopLimits(max_seconds=5, max_actions=len(book.rules), verify_poll_seconds=.001))
    result = loop.run()
    assert result["status"] == "action_limit"
    assert len(clicks) == 34
    assert planner.last_completed == "route_colossus_place"
    entries = [json.loads(line) for line in (tmp_path / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(e["status"] == "changed" for e in entries)


def test_route_audit_and_startup_reject_incomplete_live_calibration(tmp_path):
    from master_duel_advisor.route_validation import audit_route
    from master_duel_advisor.regions import Calibration
    from master_duel_advisor.cli import build_pipeline
    layout = Calibration(name="empty", regions={})
    report = audit_route(builder.build_route(), layout, tmp_path)
    assert not report["structural_ready"]
    missing = {e["region"] for e in report["missing"]}
    assert {"ui.prompt", "fact.selection.card", "fact.field.colossus.present", "action.route_space_open"} <= missing
    path = tmp_path / "calibration.json"
    path.write_text(layout.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="画面校正が不足"):
        build_pipeline(path, ROOT / "data/decks/thunder-dragon-review/cards.sqlite3",
                       ROOT / "data/decks/thunder-dragon-review/colossus-route.json")
