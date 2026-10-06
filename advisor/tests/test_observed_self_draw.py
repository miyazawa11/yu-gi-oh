"""実End辞退→陽性Drawの直接目的。unknown prompt/idleは捏造しません。"""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import build_pipeline,close_pipeline
from master_duel_advisor.draw_outcome import DrawOverlayDetector
from master_duel_advisor.image_io import read_image
from master_duel_advisor.models import Action,Observation
from master_duel_advisor.strategy_rules import RulePlanner,StrategyBook
from master_duel_advisor.telemetry import load_trials

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/solo-basic-calibration-v5"
RUN=ROOT/"artifacts/baseline-tester/SOLO_END_PILOT_v3_20261006/screenshots"


def direct_book():
    from test_response_decline import response_raw
    raw=response_raw();rule=raw["rules"][0]
    rule["logical_response_decline"]["evidence_mode"]="observed_self_draw"
    rule["expected_prompts"]=[];rule["expected_facts"]={"response.outcome.self_draw":"true"}
    return StrategyBook.model_validate(raw)


def direct_case(tmp_path):
    from test_response_decline import response_case
    tel,_,state=response_case(tmp_path);book=direct_book();rule=book.rules[0];goal=rule.logical_response_decline
    spec=goal.model_dump(mode="json");tel.active["response_decline"]=spec
    component=DrawOverlayDetector(BASE/"draw-overlay.json").provenance()
    tel.metadata["recognition_components"].update(response_goals=[spec],draw_overlay=component)
    facts={goal.outcome_fact:Observation(value="true",confidence=1,source="draw_overlay:"+component["config_sha256"],observed_at=2),
        "response.draw_overlay_diagnostic":Observation(value=json.dumps({"word_score":1.,"self_blue_ratio":.734375,
            "config_sha256":component["config_sha256"]}),confidence=0,source="diagnostic:not_a_legal_fact",observed_at=2)}
    state=state.model_copy(update={"facts":facts,"prompt":Observation(observed_at=2),"animation":Observation(observed_at=2)})
    return tel,rule,state,book


@pytest.mark.parametrize("case",["wrong_kind","wrong_outcome","none_prompt","floor_fact"])
def test_direct_mode_has_exact_declaration_scope(case):
    raw=direct_book().model_dump(mode="json");rule=raw["rules"][0]
    if case=="wrong_kind":rule["logical_response_decline"]["kind"]="opponent_summon_success"
    elif case=="wrong_outcome":rule["logical_response_decline"]["outcome"]="self_turn_notice"
    elif case=="none_prompt":rule["expected_prompts"]=["none"]
    else:rule["expected_facts"]["response.modal_absent"]="true"
    with pytest.raises(ValidationError):StrategyBook.model_validate(raw)


def test_unknown_prompt_goal_can_complete_but_does_not_allow_next_input(tmp_path):
    tel,rule,state,book=direct_case(tmp_path)
    assert state.prompt.value is None and state.animation.value is None
    assert "response.modal_absent" not in state.facts
    assert tel.goal_confirmed(rule,state)
    action=Action.model_validate(tel.current_step["action"]);planner=RulePlanner(book)
    planner.issued(action)
    assert planner.expected(action,state)
    assert planner.filter_actions(state,[action])==[]
    assert state.prompt.value is None and state.animation.value is None
    tel.complete_step("changed",rule,state,at=3)
    assert tel.records[0]["result"]=="success" and tel.records[0]["mode"]=="synthetic"
    assert tel.records[0]["response_decline"]["evidence_mode"]=="observed_self_draw"


@pytest.mark.parametrize("case",["old_end_text","old_summon_text","old_cancel","other_prompt","same_seq","no_input",
    "hash","source_hash","source_hash_suffix","stale_diag","word","blue","stale_Draw","wrong_phase","opponent","legacy_mode"])
def test_direct_positive_outcome_rejects_each_counterexample(tmp_path,case):
    tel,rule,state,book=direct_case(tmp_path);facts=dict(state.facts)
    positive=lambda:Observation(value="true",confidence=1,source="template:synthetic",observed_at=2)
    if case=="old_end_text":facts["response.prompt.opponent_turn_end"]=positive()
    elif case=="old_summon_text":facts["response.prompt.opponent_summon_success"]=positive()
    elif case=="old_cancel":facts["response.cancel_enabled.opponent_turn_end"]=positive()
    elif case=="other_prompt":state=state.model_copy(update={"prompt":positive().model_copy(update={"value":"select_card"})})
    elif case=="same_seq":state=state.model_copy(update={"sequence":tel.current_step["before_sequence"]})
    elif case=="no_input":tel.current_step["input_sent"]=False
    elif case=="source_hash":facts["response.outcome.self_draw"]=facts["response.outcome.self_draw"].model_copy(update={"source":"draw_overlay:wrong"})
    elif case=="source_hash_suffix":facts["response.outcome.self_draw"]=facts["response.outcome.self_draw"].model_copy(update={"source":facts["response.outcome.self_draw"].source+"-wrong"})
    elif case=="stale_Draw":facts["response.outcome.self_draw"]=facts["response.outcome.self_draw"].model_copy(update={"observed_at":1})
    elif case=="wrong_phase":state=state.model_copy(update={"phase":state.phase.model_copy(update={"value":"MAIN1"})})
    elif case=="opponent":state=state.model_copy(update={"turn_player":state.turn_player.model_copy(update={"value":"opponent"})})
    elif case=="legacy_mode":
        from test_response_decline import response_book
        rule=response_book().rules[0];spec=rule.logical_response_decline.model_dump(mode="json")
        tel.active["response_decline"]=spec;tel.metadata["recognition_components"]["response_goals"]=[spec]
    else:
        raw=json.loads(facts["response.draw_overlay_diagnostic"].value)
        if case=="hash":raw["config_sha256"]="wrong"
        elif case=="word":raw["word_score"]=.89
        elif case=="blue":raw["self_blue_ratio"]=.14
        facts["response.draw_overlay_diagnostic"]=facts["response.draw_overlay_diagnostic"].model_copy(update={
            "value":json.dumps(raw),"observed_at":1 if case=="stale_diag" else 2})
    state=state.model_copy(update={"facts":facts})
    assert not tel.goal_confirmed(rule,state)
    if case in {"old_end_text","old_summon_text","old_cancel","other_prompt","wrong_phase","opponent"}:
        planner=RulePlanner(book);action=Action.model_validate(tel.current_step["action"])
        assert not planner.expected(action,state)


def test_trials_use_new_declared_mode_without_reusing_old_ledger():
    planner=RulePlanner(StrategyBook.model_validate_json((BASE/"solo-route.json").read_text(encoding="utf-8")))
    trials=load_trials(BASE/"end-trials.json",planner)
    assert len(trials)==1 and trials[0]["response_decline"]["evidence_mode"]=="observed_self_draw"


def test_known_failure_background_is_diagnostic_and_prompt_remains_unknown():
    p=build_pipeline(BASE/"calibration.json",ROOT/"data/decks/thunder-dragon-review/cards.sqlite3",BASE/"solo-route.json",BASE/"ui-rules.json")
    try:
        for name in ["verify-failure-0000-last_recognized-seq23.png","verify-failure-0000-last_captured-seq24.png"]:
            state=p.perception.process(Frame(read_image(RUN/name),0,23,capture_source="saved_image"))
            assert state.phase.value=="DRAW" and state.turn_player.value=="self" and state.terminal.value is False
            assert state.prompt.value is None and state.animation.value is None
            assert state.facts["response.modal_absent"].confidence==0
            assert state.facts["response.modal_absent"].source=="diagnostic:background_not_completion"
            assert json.loads(state.facts["response.modal_background_diagnostic"].value)["raw_scores"]["true"]<.98
            assert state.facts["response.outcome.self_draw"].value=="true"
            assert p.planner.filter_actions(state,state.visible_actions)==[]
    finally:close_pipeline(p)


def test_draw_band_with_remaining_cancel_is_a_positive_conflict():
    p=build_pipeline(BASE/"calibration.json",ROOT/"data/decks/thunder-dragon-review/cards.sqlite3",BASE/"solo-route.json",BASE/"ui-rules.json")
    try:
        after=read_image(RUN/"verify-failure-0000-last_recognized-seq23.png").copy()
        before=read_image(RUN/"before-0000.png")
        after[674:688,506:584]=before[674:688,506:584]
        state=p.perception.process(Frame(after,0,1,capture_source="saved_image"))
        raw=json.loads(state.facts["response.draw_overlay_diagnostic"].value)
        assert raw["word_score"]==1 and raw["self_blue_ratio"]>.15
        assert state.facts["response.cancel_enabled.opponent_turn_end"].value=="true"
        assert state.facts["response.outcome.self_draw"].value is None
        assert state.phase.value is None
    finally:close_pipeline(p)
