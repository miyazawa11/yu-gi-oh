"""実失敗画像＋原receiptを読み再生。UI入力/原時計/元画像変更なし。"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import build_pipeline,close_pipeline
from master_duel_advisor.image_io import read_image
from master_duel_advisor.hand_search import activation_parent_valid
from master_duel_advisor.models import Observation
from master_duel_advisor.strategy_rules import RulePlanner

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/dragondark-hand-search-calibration-v4"
RUN=ROOT/"artifacts/baseline-tester/DRAGONDARK_HAND_SEARCH_PILOT_v2_20261006"


@pytest.fixture
def current_case():
    """合成active/new specと元途中画像。閉じた実trialの再開ではありません。"""
    p=build_pipeline(BASE/"calibration.json",ROOT/"data/decks/thunder-dragon-review/cards.sqlite3",BASE/"solo-route.json",BASE/"ui-rules.json")
    context=deepcopy(json.loads((RUN/"logical-actions.jsonl").read_text(encoding="utf-8").splitlines()[0]))
    context["result"]=None
    goal=p.perception.hand_goal.model_copy(update={"own_chain_mode":"parent_activation_ui"})
    p.perception.configure_hand_search(goal,BASE)
    p.planner.book.rules[:]=[r.model_copy(update={"logical_hand_search_confirmation":goal})
        if r.logical_hand_search_confirmation else r for r in p.planner.book.rules]
    p.planner=RulePlanner(p.planner.book)
    context["hand_search_confirmation"]=goal.model_dump(mode="json")
    step=context["steps"][0]
    after=json.loads((RUN/"actions.jsonl").read_text(encoding="utf-8").splitlines()[0])["state_after"]
    frame=Frame(read_image(RUN/"screenshots/after-0001.png"),after["captured_at"],after["sequence"],
        capture_source="live_mss",capture_rect=tuple(step["client_rect"]),input_epoch=step["input_epoch"])
    p.perception.inspect_client_rect=frame.capture_rect
    try:yield p,goal,context,frame
    finally:close_pipeline(p)


@pytest.mark.parametrize("case",["valid","closed","missing_sent","unverified_epoch","wrong_spec","duplicate_cancel",
    "wrong_epoch","old_sequence","old_clock","saved","different_client","wrong_profile","stale_source",
    "wrong_parent_point","wrong_proof_client","different_parent_purpose"])
def test_parent_receipt_permission_boundaries(current_case,case):
    p,goal,context,frame=current_case;step=context["steps"][0]
    if case=="closed":context["result"]="interrupted"  # 元実trial同様、救済再開禁止。
    elif case=="missing_sent":step["input_sent"]=None
    elif case=="unverified_epoch":step["input_epoch_verified"]=False
    elif case=="wrong_spec":context["hand_search_confirmation"]["card_id"]="other"
    elif case=="duplicate_cancel":context["steps"].append(deepcopy(step))
    elif case=="wrong_epoch":frame=replace(frame,input_epoch=frame.input_epoch+1)
    elif case=="old_sequence":frame=replace(frame,sequence=step["before_sequence"])
    elif case=="old_clock":frame=replace(frame,captured_at=step["capture_monotonic"])
    elif case=="saved":frame=replace(frame,capture_source="image")
    elif case=="different_client":frame=replace(frame,capture_rect=(0,0,1280,720))
    elif case=="wrong_profile":step["action"]["hand_search_proof"]["profile_sha256"]="wrong"
    elif case=="stale_source":step["hand_before"]["facts"][goal.source_ready_fact]["observed_at"]-=1
    elif case=="wrong_parent_point":step["screen_point"][0]+=1
    elif case=="wrong_proof_client":step["action"]["hand_search_proof"]["client_rect"][0]+=1
    elif case=="different_parent_purpose":context["logical_action"]="different-purpose"
    assert activation_parent_valid(context,goal,frame,p.perception.hand_vision.sha256,
        logical_action="dragondark_hand_search")== (case=="valid")


@pytest.mark.parametrize("field,value,source",[("terminal",True,"synthetic"),("turn_player","opponent","synthetic"),
    ("phase","DRAW","synthetic"),("animation",True,"synthetic"),
    ("phase",None,"conflicting_positive_evidence"),("turn_player",None,"conflicting_positive_evidence"),
    ("animation",None,"conflicting_positive_evidence")])
def test_current_known_or_merged_conflict_never_allowed_by_unknown_exception(current_case,field,value,source):
    p,goal,context,frame=current_case
    state=p.perception.process(frame,hand_episode_context=context)
    action=next(a for a in state.visible_actions if a.source_region==goal.cancel_region)
    rule=p.planner.rule_for(action)
    state=state.model_copy(update={field:Observation(value=value,confidence=1 if value is not None else 0,
        source=source,observed_at=frame.captured_at)})
    assert rule.missing(state,.98,action=action)


def test_unknown_phase_idle_permission_is_actually_accepted_by_new_strict_rule(current_case):
    p,goal,context,frame=current_case
    state=p.perception.process(frame,hand_episode_context=context)
    action=next(a for a in state.visible_actions if a.source_region==goal.cancel_region)
    assert p.planner.rule_for(action).missing(state,.98,action=action)==[]
    assert state.phase.value is None and state.animation.value is None


def test_current_own_reply_crosses_generator_strict_and_ui_policy_with_parent_follow(current_case):
    """原frameの再生＋合成判断clock。実機trial/入力/E2Eではありません。"""
    p,goal,context,frame=current_case
    state=p.perception.process(frame,hand_episode_context=context)
    parent=next(r for r in p.planner.book.rules if r.source_region==goal.activate_region)
    p.planner.last_completed=parent.id
    p.clock=lambda:frame.captured_at+.01
    generate=p.rules.generate
    p.rules.generate=lambda s,now:generate(s,frame.captured_at+.01)
    result=p.process(frame,observed_state=state)
    assert result["recommendation"]["action"]["source_region"]==goal.cancel_region
    assert result["state"]["phase"]["value"] is None
    assert result["state"]["animation"]["value"] is None


@pytest.mark.parametrize("case",["closed_parent","caption_missing"])
def test_positive_main1_does_not_escape_new_mode_into_old_idle_branch(current_case,monkeypatch,case):
    p,goal,context,frame=current_case
    if case=="closed_parent":context["result"]="interrupted"
    else:monkeypatch.setattr(p.perception.hand_cancel_caption,"detect",lambda pixels:SimpleNamespace(passed=False,score=0,
        config_sha256="missing",click_point=(545,681)))
    observed={"fact.inspect_context.main1":Observation(value="true",confidence=1,observed_at=frame.captured_at)}
    actions=[];proposed={}
    p.perception._hand_search_observations(frame,observed,actions,proposed,context)
    assert not any(a.source_region==goal.cancel_region for a in actions)
    assert "ui.animation" not in proposed and "phase" not in proposed


@pytest.mark.parametrize("case",["valid","missing_parent","already_sent","wrong_caption_hash","missing_caption",
    "wrong_permission_hash","different_purpose"])
def test_input_coordinate_guard_joins_exact_parent_and_current_caption(current_case,case):
    from master_duel_advisor.agent_loop import AgentLoop,LoopLimits
    p,goal,context,frame=current_case
    state=p.perception.process(frame,hand_episode_context=context)
    action=next(a for a in state.visible_actions if a.source_region==goal.cancel_region)
    context["steps"].append({"action":action.model_dump(mode="json"),"before_sequence":frame.sequence,"input_sent":None})
    loop=object.__new__(AgentLoop)
    loop.pipeline=p;loop.calibration=p.perception.calibration;loop.telemetry=SimpleNamespace(active=context)
    loop.screen_rect=frame.capture_rect;loop.inspection_goal=None;loop.inspection_live_bound=True
    loop.limits=LoopLimits();loop.clock=lambda:frame.captured_at+.01
    if case=="missing_parent":context["steps"][0]["input_sent"]=None
    elif case=="already_sent":context["steps"][1]["input_sent"]=True
    elif case=="wrong_caption_hash":
        obs=state.facts["hand_search.own_chain_caption"];raw=json.loads(obs.value);raw["config_sha256"]="bad"
        state.facts["hand_search.own_chain_caption"]=obs.model_copy(update={"value":json.dumps(raw)})
    elif case=="missing_caption":state.facts.pop("hand_search.own_chain_caption")
    elif case=="wrong_permission_hash":
        for key in [goal.own_chain_fact,"hand_search.own_chain_permission"]:
            state.facts[key]=state.facts[key].model_copy(update={"source":"hand_search:wrong"})
    elif case=="different_purpose":context["logical_action"]="other"
    if case=="valid":assert loop._coordinates(action,frame.pixels.shape,frame=frame,state=state)==(-1373,1498)
    else:
        with pytest.raises(ValueError,match="自己chain"):
            loop._coordinates(action,frame.pixels.shape,frame=frame,state=state)


@pytest.mark.parametrize("case",["valid","permission_missing","caption_missing","bad_caption_hash","old_caption",
    "old_parent","duplicate_sent","conflicting_phase","conflicting_animation","playing","different_purpose"])
def test_new_mode_goal_joins_unknown_chain_before_to_actual_parent_receipt(tmp_path,case):
    """全receipt/clock/sceneがsynthetic。原実機pilotの救済ではありません。"""
    from test_hand_search_integration import synthetic_hand_case,SHA
    tel,rules,after=synthetic_hand_case(tmp_path)
    goal=rules[0].logical_hand_search_confirmation.model_copy(update={"own_chain_mode":"parent_activation_ui"})
    rules=[r.model_copy(update={"logical_hand_search_confirmation":goal}) for r in rules]
    tel.active["hand_search_confirmation"]=goal.model_dump(mode="json")
    component=tel.metadata["recognition_components"]["hand_search"]
    component.update(goal=goal.model_dump(mode="json"),own_chain_cancel_caption={"config_sha256":"synthetic-caption"})
    step=tel.active["steps"][1];before=step["hand_before"]
    for field in ["phase","turn_player","animation"]:
        before[field]={"value":None,"confidence":0,"source":"unknown","observed_at":2.}
    before["facts"]["hand_search.own_chain_permission"]={"value":"true","confidence":1,"source":"hand_search:"+SHA,"observed_at":2.}
    before["facts"]["hand_search.own_chain_caption"]={"value":json.dumps({"score":1.,"click_point":[545,681],"config_sha256":"synthetic-caption"}),
        "confidence":0,"source":"diagnostic:not_a_legal_fact","observed_at":2.}
    if case=="permission_missing":before["facts"].pop("hand_search.own_chain_permission")
    elif case=="caption_missing":before["facts"].pop("hand_search.own_chain_caption")
    elif case=="bad_caption_hash":component["own_chain_cancel_caption"]["config_sha256"]="other"
    elif case=="old_caption":before["facts"]["hand_search.own_chain_caption"]["observed_at"]=1.
    elif case=="old_parent":tel.active["steps"][0]["action"]["hand_search_proof"]["frame_seq"]=9
    elif case=="duplicate_sent":tel.active["steps"].append(deepcopy(tel.active["steps"][-1]))
    elif case=="conflicting_phase":before["phase"]["source"]="conflicting_positive_evidence"
    elif case=="conflicting_animation":before["animation"]["source"]="conflicting_positive_evidence"
    elif case=="playing":before["animation"].update(value=True,confidence=1)
    elif case=="different_purpose":tel.active["logical_action"]="different"
    assert tel.hand_step_confirmed(rules[-1],after)==(case=="valid")


def test_current_exact_own_chain_and_parent_receipt_allow_cancel_without_inventing_phase_or_idle():
    p=build_pipeline(BASE/"calibration.json",ROOT/"data/decks/thunder-dragon-review/cards.sqlite3",BASE/"solo-route.json",BASE/"ui-rules.json")
    try:
        context=json.loads((RUN/"logical-actions.jsonl").read_text(encoding="utf-8").splitlines()[0])
        context=deepcopy(context);context["result"]=None
        goal=p.perception.hand_goal.model_copy(update={"own_chain_mode":"parent_activation_ui"})
        # synthetic active-parent/new spec fixture。原interrupted trialを再開した評価ではありません。
        p.perception.configure_hand_search(goal,BASE);context["hand_search_confirmation"]=goal.model_dump(mode="json")
        step=context["steps"][0];after=json.loads((RUN/"actions.jsonl").read_text(encoding="utf-8").splitlines()[0])["state_after"]
        # 原runtime snapshot/mono/seqをそのまま使い、入力は呼びません。
        frame=Frame(read_image(RUN/"screenshots/after-0001.png"),after["captured_at"],after["sequence"],
            capture_source="live_mss",capture_rect=tuple(step["client_rect"]),input_epoch=step["input_epoch"])
        p.perception.inspect_client_rect=frame.capture_rect
        state=p.perception.process(frame,hand_episode_context=context)
        assert state.phase.value is None and state.animation.value is None
        assert state.prompt.value=="hand.dragondark.own_chain"
        assert state.facts["hand_search.own_chain_permission"].value=="true"
        assert any(a.type.value=="CANCEL" and a.source_region==goal.cancel_region for a in state.visible_actions)
    finally:close_pipeline(p)
