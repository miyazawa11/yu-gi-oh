"""意味別辞退・共通book・入力receiptの合成境界。実機標本ではありません。"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import time

import numpy as np
import pytest
from pydantic import ValidationError

from master_duel_advisor.capture import Frame
from master_duel_advisor.models import Action, GameState, Observation
from master_duel_advisor.pipeline import Pipeline
from master_duel_advisor.strategy_rules import LogicalResponseDecline, RulePlanner, StrategyBook
from master_duel_advisor.telemetry import ActionTelemetry, load_trials
from master_duel_advisor.ui_policy import UiPolicy, UiRule

ROOT = Path(__file__).resolve().parents[1]


def response_raw(kind="opponent_turn_end"):
    goal = LogicalResponseDecline(kind=kind, outcome="self_draw" if kind.endswith("end") else "opponent_main1",
                                 cancel_region="action.cancel_" + kind)
    return {"format":"deck-strategy-v1", "name":"合成辞退", "source":"synthetic",
        "audit_profile":"response_decline", "inference_mode":"strict", "rules":[{
        "id":"decline_"+kind, "description":"任意発動を辞退", "type":"CANCEL", "source_region":goal.cancel_region,
        "priority":100, "players":["opponent"], "phases":[goal.before_phase.value], "prompt":goal.semantic_prompt,
        "observed_facts":{goal.prompt_fact:"true",goal.cancel_fact:"true"}, "expected_prompts":["none"],
        "expected_facts":{goal.modal_absent_fact:"true",goal.outcome_fact:"true"},
        "logical_action":"decline_"+kind, "logical_category":"CHAIN", "logical_start":True,"logical_end":True,
        "logical_response_decline":goal.model_dump(mode="json")} ]}


def response_book(kind="opponent_turn_end"):
    return StrategyBook.model_validate(response_raw(kind))


def response_state(rule, at, after=False):
    obs=lambda v: Observation(value=v,confidence=1 if v is not None else 0,observed_at=at,source="template:synthetic")
    goal=rule.logical_response_decline
    phase="DRAW" if after and goal.outcome=="self_draw" else goal.before_phase.value
    facts={goal.modal_absent_fact:obs("true"),goal.outcome_fact:obs("true")} if after else {
        goal.prompt_fact:obs("true"),goal.cancel_fact:obs("true")}
    return GameState(sequence=int(at*10), captured_at=at, phase=obs(phase),
        turn_player=obs("self" if after and goal.kind.endswith("end") else "opponent"),
        animation=obs(True if after and goal.kind.endswith("end") else False), terminal=obs(False),
        prompt=obs("none" if after else goal.semantic_prompt),facts=facts)


@pytest.mark.parametrize("kind",["opponent_turn_end","opponent_summon_success"])
def test_response_declaration_and_policy_are_typed(kind):
    book=response_book(kind);rule=book.rules[0]
    policy=UiPolicy(rules=[UiRule(prompt=rule.prompt,type=rule.type,source_region=rule.source_region)])
    policy.validate_responses(book)
    assert rule.card_id is None and rule.target is None
    with pytest.raises(ValidationError): LogicalResponseDecline(kind=kind,outcome="opponent_main1" if kind.endswith("end") else "self_draw",cancel_region=rule.source_region)
    with pytest.raises(ValueError): UiPolicy().validate_responses(book)
    with pytest.raises(ValueError): UiPolicy(rules=policy.rules*2).validate_responses(book)


@pytest.mark.parametrize("change",[{"type":"CONFIRM"},{"card_id":"12950"},{"prompt":"chain.select"},
    {"players":["self"]},{"phases":["MAIN1"]},{"logical_start":False},{"logical_end":False},
    {"expected_facts":{}},{"observed_facts":{}},{"facts":{"hidden.cid":"12950"}},
    {"logical_count_fact":"count.self.hand"},{"logical_phase":"DRAW"}])
def test_response_rejects_semantic_or_goal_weakening(change):
    raw=response_raw();raw["rules"][0].update(change)
    with pytest.raises(ValidationError): StrategyBook.model_validate(raw)


def combined_raw():
    raw=response_raw();raw["audit_profile"]="solo_basic_operations"
    normal=json.loads((ROOT/"artifacts/ash-normal-inspect-calibration-v5/normal-route.json").read_text(encoding="utf-8"))
    phase=json.loads((ROOT/"artifacts/phase-only-calibration/phase-route.json").read_text(encoding="utf-8"))
    raw["rules"] += normal["rules"]+phase["rules"]+response_raw("opponent_summon_success")["rules"]
    return raw


def test_combined_validator_is_rule_order_independent_and_keeps_old_rules():
    raw=combined_raw();book=StrategyBook.model_validate(raw)
    raw["rules"]=list(reversed(raw["rules"]))
    reverse=StrategyBook.model_validate(raw)
    assert {r.id:r.model_dump() for r in book.rules}=={r.id:r.model_dump() for r in reverse.rules}
    raw["rules"]=raw["rules"][:-1]
    with pytest.raises(ValidationError): StrategyBook.model_validate(raw)


def test_pending_other_group_blocks_response():
    book=StrategyBook.model_validate(combined_raw());planner=RulePlanner(book)
    rule=next(r for r in book.rules if r.logical_response_decline)
    state=response_state(rule,time.monotonic())
    action=Action(type="CANCEL",confidence=1,observed_at=state.captured_at,source_region=rule.source_region)
    normal=next(r for r in book.rules if r.logical_inspect_confirmation)
    planner.issued(Action(type=normal.type,card_id=normal.card_id,confidence=1,observed_at=state.captured_at,source_region=normal.source_region))
    assert not planner.filter_actions(state,[action])
    assert "pending_verification" in planner.blocked[rule.source_region]


@pytest.mark.parametrize("policy_ok,strict_ok,deadline",[(True,True,False),(False,True,False),(True,False,False),(False,True,True),(True,False,True)])
def test_pipeline_requires_both_gates_even_at_deadline(policy_ok,strict_ok,deadline):
    book=response_book();rule=book.rules[0];state=response_state(rule,time.monotonic())
    if not strict_ok:state=state.model_copy(update={"facts":{}})
    action=Action(type="CANCEL",confidence=1,source_region=rule.source_region,observed_at=state.captured_at)
    state=state.model_copy(update={"visible_actions":[action]})
    perception=SimpleNamespace(process=lambda f:state,cards=SimpleNamespace(get=lambda c:None),cache_hits=0,recognized_regions=0)
    policy=UiPolicy(rules=[UiRule(prompt=rule.prompt,type=rule.type,source_region=rule.source_region)] if policy_ok else [])
    pipe=Pipeline(perception,planner=RulePlanner(book),ui_policy=policy)
    if deadline:pipe.decision_started=time.monotonic()-20
    result=pipe.process(None)
    assert bool(result["recommendation"]["action"])==(policy_ok and strict_ok)


def response_case(tmp_path,kind="opponent_turn_end"):
    rule=response_book(kind).rules[0];before=response_state(rule,1);after=response_state(rule,2,after=True)
    rect=(100,200,1380,920)
    layout={"regions":{rule.source_region:{"kind":"action","card_id":None,"target":None,
        "rect":{"x":.3,"y":.8,"width":.2,"height":.1}}}}
    tel=ActionTelemetry(tmp_path,clock=lambda:3,mode="synthetic")
    tel.configure(capture={"rect":rect},calibration=layout,recognition_components={
        "response_goals":[rule.logical_response_decline.model_dump(mode="json")],"files":{"synthetic-source":"synthetic-hash"}})
    frame=Frame(np.zeros((720,1280,3),np.uint8),1,10,capture_start=.9,capture_end=1,capture_source="live_mss",capture_rect=rect,input_epoch=99)
    action=Action(type="CANCEL",confidence=1,source_region=rule.source_region,observed_at=1)
    tel.begin_step(action,rule,before,frame,{})
    tel.input_result(True,(610,810));tel.current_step.update(input_epoch=100,input_epoch_verified=True)
    return tel,rule,after


@pytest.mark.parametrize("kind",["opponent_turn_end","opponent_summon_success"])
def test_response_goal_actual_cancel_and_positive_outcome(tmp_path,kind):
    tel,rule,after=response_case(tmp_path,kind)
    assert tel.goal_confirmed(rule,after)
    planner=RulePlanner(response_book(kind));action=Action.model_validate(tel.current_step["action"])
    planner.issued(action)
    assert planner.expected(action,after)  # End Drawのplayingをidleへ変換しません。
    tel.complete_step("changed",rule,after,at=2)
    assert tel.records[0]["result"]=="success" and tel.records[0]["mode"]=="synthetic"


@pytest.mark.parametrize("case",["unknown_sent","false_sent","epoch_unknown","epoch_unverified","offline",
    "wrong_client","wrong_point","wrong_cid","wrong_type","same_seq","stale_prompt","stale_fact",
    "missing_modal","missing_outcome","wrong_outcome","before_unknown_phase","wrong_before_prompt",
    "component_missing","goal_mixed","integrity_changed","extra_input","capture_seq_mismatch",
    "capture_epoch_missing","same_clock","low_action_score"])
def test_response_goal_each_missing_proof_fails_closed(tmp_path,case):
    tel,rule,state=response_case(tmp_path);step=tel.current_step;goal=rule.logical_response_decline
    if case=="unknown_sent":step["input_sent"]=None
    elif case=="false_sent":step["input_sent"]=False
    elif case=="epoch_unknown":step["input_epoch"]=None
    elif case=="epoch_unverified":step["input_epoch_verified"]=False
    elif case=="offline":step["capture_source"]="saved_image"
    elif case=="wrong_client":step["capture_rect"]=[101,200,1381,920]
    elif case=="wrong_point":step["screen_point"]=[100,200]
    elif case=="wrong_cid":step["action"]["card_id"]="12950"
    elif case=="wrong_type":step["action"]["type"]="CONFIRM"
    elif case=="same_seq":state=state.model_copy(update={"sequence":10})
    elif case=="stale_prompt":state=state.model_copy(update={"prompt":state.prompt.model_copy(update={"observed_at":1})})
    elif case=="stale_fact":state=state.model_copy(update={"facts":{**state.facts,goal.outcome_fact:state.facts[goal.outcome_fact].model_copy(update={"observed_at":1})}})
    elif case=="missing_modal":state=state.model_copy(update={"facts":{goal.outcome_fact:state.facts[goal.outcome_fact]}})
    elif case=="missing_outcome":state=state.model_copy(update={"facts":{goal.modal_absent_fact:state.facts[goal.modal_absent_fact]}})
    elif case=="wrong_outcome":state=state.model_copy(update={"phase":state.phase.model_copy(update={"value":"MAIN1"})})
    elif case=="before_unknown_phase":step["response_before"]["phase"].update(value=None,confidence=0)
    elif case=="wrong_before_prompt":step["response_before"]["prompt"]["value"]="response.opponent_summon_success"
    elif case=="component_missing":tel.metadata["recognition_components"]["files"]={}
    elif case=="goal_mixed":tel.active["response_decline"]["kind"]="opponent_summon_success"
    elif case=="integrity_changed":tel.metadata["data_integrity"]=False
    elif case=="extra_input":tel.active["steps"].append(deepcopy(step))
    elif case=="capture_seq_mismatch":step["capture_sequence"]=11
    elif case=="capture_epoch_missing":step["capture_input_epoch"]=None
    elif case=="same_clock":state=state.model_copy(update={"captured_at":1})
    elif case=="low_action_score":step["action"]["confidence"]=.979
    assert not tel.goal_confirmed(rule,state)


def test_trial_preserves_typed_response_goal(tmp_path):
    path=tmp_path/"trials.json";book=response_book()
    path.write_text(json.dumps([book.rules[0].logical_action]),encoding="utf-8")
    assert load_trials(path,RulePlanner(book))[0]["response_decline"]==book.rules[0].logical_response_decline.model_dump(mode="json")


def test_summon_to_next_end_is_typed_without_modal_absent(tmp_path):
    raw=response_raw("opponent_summon_success");item=raw["rules"][0]
    item["logical_response_decline"]["outcome"]="opponent_end_response"
    item["expected_prompts"]=["response.opponent_turn_end"]
    item["expected_facts"]={"response.prompt.opponent_turn_end":"true","response.outcome.opponent_end_response":"true"}
    rule=StrategyBook.model_validate(raw).rules[0]
    tel,_,_=response_case(tmp_path,"opponent_summon_success")
    spec=rule.logical_response_decline.model_dump(mode="json")
    tel.active["response_decline"]=spec;tel.metadata["recognition_components"]["response_goals"]=[spec]
    state=response_state(response_book().rules[0],2)
    obs=lambda v:Observation(value=v,confidence=1,observed_at=2,source="template:synthetic")
    state=state.model_copy(update={"facts":{"response.prompt.opponent_turn_end":obs("true"),
        "response.outcome.opponent_end_response":obs("true")}})
    assert "response.modal_absent" not in state.facts
    assert tel.goal_confirmed(rule,state)
    closed=state.model_copy(update={"prompt":obs("none")})
    assert not tel.goal_confirmed(rule,closed)
    wrong=state.model_copy(update={"phase":obs("MAIN1")})
    assert not tel.goal_confirmed(rule,wrong)
    planner=RulePlanner(StrategyBook.model_validate(raw))
    assert planner.expected(Action.model_validate(tel.current_step["action"]),state)


def test_child_timing_union_excludes_poll_and_keeps_parent_overlap(tmp_path):
    tel,rule,state=response_case(tmp_path)
    tel.spans=[{"stage":"capture","start":.9,"end":1},
        {"stage":"input","start":1,"end":1.1},{"stage":"pre_input_control","start":1.01,"end":1.04},
        {"stage":"verify","start":1.1,"end":2},{"stage":"poll_wait","start":1.1,"end":1.3},
        {"stage":"recognition","start":1.3,"end":1.5},{"stage":"predicate","start":1.5,"end":1.55}]
    tel.complete_step("changed",rule,state,at=2)
    row=tel.records[0]
    assert row["system_internal_ms"]==pytest.approx(450)
    assert row["poll_wait_ms"]==pytest.approx(200)
    assert row["verification_unmeasured_ms"]==pytest.approx(450)
    assert row["verification_residual_ms"]==pytest.approx(650)
    assert row["child_stage_ms"]["pre_input_control"]==pytest.approx(30)


@pytest.mark.parametrize("source",["saved_image","saved_video","unclassified"])
def test_response_saved_capture_cannot_receive_input_coordinates(tmp_path,source):
    from test_agent_loop import setup
    loop,_,_=setup(tmp_path)
    rule=response_book().rules[0]
    loop.pipeline.perception.response_goals=(rule.logical_response_decline,)
    loop.calibration=loop.calibration.model_copy(update={"regions":{rule.source_region:loop.calibration.regions["action.confirm"]}})
    state=response_state(rule,1)
    frame=Frame(np.zeros((720,1280,3),np.uint8),1,10,capture_source=source,capture_rect=loop.screen_rect,input_epoch=10)
    action=Action(type="CANCEL",confidence=1,source_region=rule.source_region,observed_at=1)
    with pytest.raises(ValueError):loop._coordinates(action,frame.pixels.shape,frame=frame,state=state)


@pytest.mark.parametrize("reverse,failed",[(False,False),(True,False),(True,True)])
def test_timing_failure_order_and_nested_guard_are_unioned(tmp_path,reverse,failed):
    tel,rule,state=response_case(tmp_path)
    tel.spans=[{"stage":"verify","start":1,"end":2},
        {"stage":"capture","start":.9,"end":1},
        {"stage":"poll_wait","start":1,"end":1.2},
        {"stage":"verify_input_control","start":1.2,"end":1.3},
        {"stage":"frontmost_stop_check","start":1.22,"end":1.25},
        {"stage":"predicate","start":1.3,"end":1.3}]
    if reverse:tel.spans.reverse()
    if failed:tel.finish("interrupted","Verification failure","test",end=2)
    else:tel.complete_step("changed",rule,state,at=2)
    row=tel.records[0]
    assert row["system_internal_ms"]==pytest.approx(200)
    assert row["poll_wait_ms"]==pytest.approx(200)
    assert row["verification_unmeasured_ms"]==pytest.approx(700)
    assert row["child_stage_ms"]["predicate"]==0
