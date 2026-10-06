"""hand goalの合成receipt/状態統合。実UI入力/実機標本ではありません。"""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.models import Action,GameState,Observation,HandSearchCoordinateProof
from master_duel_advisor.strategy_rules import StrategyBook
from master_duel_advisor.telemetry import ActionTelemetry

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/dragondark-hand-search-calibration-v3"
RECT=(100,200,1380,920)
SHA="synthetic-hand-profile"


def hand_book():
    return StrategyBook.model_validate(json.loads((BASE/"solo-route.json").read_text(encoding="utf-8")))


def hand_state(rule,at,seq,facts,prompt):
    def obs(value,source="hand_search:"+SHA):
        return Observation(value=value,confidence=1 if value is not None else 0,observed_at=at,source=source)
    return GameState(sequence=seq,captured_at=at,phase=obs("MAIN1"),turn_player=obs("self"),
        prompt=obs(prompt),animation=obs(False),terminal=obs(False),facts={k:obs(v) for k,v in facts.items()})


def synthetic_hand_case(tmp_path):
    """原画像/原時計には触れない、3child実送信フラグの合成fixture。"""
    rules=[r for r in hand_book().rules if r.logical_hand_search_confirmation]
    goal=rules[0].logical_hand_search_confirmation;spec=goal.model_dump(mode="json")
    states=[
        hand_state(rules[0],1.,10,{goal.source_ready_fact:"true",goal.detail_fact:"13906","hand_search.layout":"hand7-slot3"},"hand.dragondark.effect_menu"),
        hand_state(rules[1],2.,20,{goal.own_chain_fact:"true"},"hand.dragondark.own_chain"),
        hand_state(rules[2],4.,40,{goal.result_ready_fact:"true",goal.detail_fact:None},"hand.dragondark.result_ready"),
        hand_state(rules[2],5.,50,{goal.result_selected_fact:"true",goal.detail_fact:"13906"},"hand.dragondark.result_selected")]
    states[2].facts["inspect_context.detail_blank"]=Observation(value="true",confidence=1,observed_at=4.,source="template:synthetic-blank")
    episode={"action_id":None,"profile_sha256":SHA,"layout":"hand7-slot3","failed":None,"ready":True,
        "anchor":{"seq":25,"at":2.5,"bbox":[582,447,118,174],"cid":"13906"},
        "handoff":{"seq":35,"at":3.5,"bbox":[589,595,103,151]},
        "last_seq":40,"last_at":4.,"trace":[{"seq":35,"at":3.5}],
        "current_ready_geometry":{"role":"handoff_visible_interior","bbox":[600,610,80,95],"point":[640,657]},
        "current_selected_geometry":{"bbox":[589,555,103,150]}}
    tel=ActionTelemetry(tmp_path,clock=lambda:6,mode="synthetic")
    tel.configure(capture={"rect":RECT},recognition_components={"hand_search":{"profile_sha256":SHA,"goal":spec}})
    for index,rule in enumerate(rules):
        before=states[index];point=(640,522) if index==0 else (545,681) if index==1 else (640,657)
        box=(601,487,78,91) if index==0 else (600,610,80,95)
        proof=None if index==1 else HandSearchCoordinateProof(action_type=rule.type.value,layout_id="hand7-slot3",
            frame_seq=before.sequence,observed_at=before.captured_at,client_rect=RECT,
            evidence_bbox=box,point=point,profile_sha256=SHA)
        action=Action(type=rule.type,card_id=rule.card_id,target=rule.target,confidence=1,
            source_region=rule.source_region,observed_at=before.captured_at,hand_search_proof=proof)
        frame=Frame(np.zeros((720,1280,3),np.uint8),before.captured_at,before.sequence,
            capture_start=before.captured_at-.01,capture_end=before.captured_at,capture_source="live_mss",capture_rect=RECT,input_epoch=99+index)
        tel.begin_step(action,rule,before,frame,{})
        episode["action_id"]=tel.active["action_id"]
        tel.active["hand_episode"]=deepcopy(episode)
        # 第3child直前の可視geometryを実begin_stepのsnapshotとは分離せず保持します。
        tel.input_result(True,(RECT[0]+point[0],RECT[1]+point[1]))
        tel.current_step.update(input_epoch=100+index,input_epoch_verified=True)
        if index<2:tel.complete_step("changed",rule,states[index+1],at=states[index+1].captured_at)
    episode.update(last_seq=50,last_at=5.)
    tel.active["hand_episode"]=deepcopy(episode)
    return tel,rules,states[-1]


def test_normal_three_child_hand_goal_success_is_one_parent_purpose(tmp_path):
    tel,rules,after=synthetic_hand_case(tmp_path)
    assert tel.hand_step_confirmed(rules[-1],after)
    assert tel.goal_confirmed(rules[-1],after)
    tel.complete_step("changed",rules[-1],after,at=5.)
    assert len(tel.records)==1 and tel.records[0]["result"]=="success"
    assert tel.records[0]["input_count"]==3


@pytest.mark.parametrize("case",["same_spec_other_goal","third_ready_missing","different_safe_point","different_handoff",
    "stale_before_detail","blank_missing","missing_inspect_receipt","same_sequence","stale_final_detail",
    "neighbor_selected_geometry","missing_selected_geometry","wrong_profile_hash","wrong_chain",
    "expired_handoff","epoch_unverified"])
def test_hand_goal_each_broken_receipt_join_is_rejected(tmp_path,case):
    tel,rules,after=synthetic_hand_case(tmp_path);step=tel.current_step;goal=rules[-1].logical_hand_search_confirmation
    if case=="same_spec_other_goal":tel.active["logical_action"]="different-parent-purpose"
    elif case=="third_ready_missing":step["hand_before"]["facts"].pop(goal.result_ready_fact)
    elif case=="different_safe_point":
        step["action"]["hand_search_proof"]["point"][0]+=1;step["screen_point"][0]+=1
    elif case=="different_handoff":
        tel.active["hand_episode"]["handoff"]["bbox"][0]+=150
    elif case=="stale_before_detail":step["hand_before"]["facts"][goal.detail_fact].update(value="13906",confidence=1)
    elif case=="blank_missing":step["hand_before"]["facts"].pop("inspect_context.detail_blank")
    elif case=="missing_inspect_receipt":step["input_sent"]=None
    elif case=="same_sequence":after=after.model_copy(update={"sequence":40})
    elif case=="stale_final_detail":after.facts[goal.detail_fact]=after.facts[goal.detail_fact].model_copy(update={"observed_at":1.})
    elif case=="neighbor_selected_geometry":tel.active["hand_episode"]["current_selected_geometry"]["bbox"][0]+=150
    elif case=="missing_selected_geometry":tel.active["hand_episode"].pop("current_selected_geometry")
    elif case=="wrong_profile_hash":step["action"]["hand_search_proof"]["profile_sha256"]="other-profile"
    elif case=="wrong_chain":tel.active["steps"][1]["hand_before"]["facts"].pop(goal.own_chain_fact)
    elif case=="expired_handoff":tel.active["hand_episode"]["handoff"]["at"]=1.
    elif case=="epoch_unverified":step["input_epoch_verified"]=False
    assert not tel.goal_confirmed(rules[-1],after),case


@pytest.mark.parametrize("case",["allowed_unknown","playing","other_action","other_source","other_prompt","missing_proof",
    "stale_proof","missing_ready","missing_blank","conflicting_animation"])
def test_only_received_hand_inspect_allows_unknown_animation_without_relabeling(tmp_path,case):
    from master_duel_advisor.strategy_rules import RulePlanner
    tel,rules,_=synthetic_hand_case(tmp_path);rule=rules[-1]
    state=GameState.model_validate(tel.current_step["hand_before"])
    state=state.model_copy(update={"animation":Observation(observed_at=state.captured_at)})
    action=Action.model_validate(tel.current_step["action"])
    if case=="playing":state=state.model_copy(update={"animation":Observation(value=True,confidence=1,observed_at=4.)})
    elif case=="other_action":action=action.model_copy(update={"type":"ACTIVATE"})
    elif case=="other_source":action=action.model_copy(update={"source_region":rules[0].source_region})
    elif case=="other_prompt":state=state.model_copy(update={"prompt":Observation(value="none",confidence=1,observed_at=4.)})
    elif case=="missing_proof":action=action.model_copy(update={"hand_search_proof":None})
    elif case=="stale_proof":action=action.model_copy(update={"hand_search_proof":action.hand_search_proof.model_copy(update={"frame_seq":39})})
    elif case=="missing_ready":state.facts.pop(rule.logical_hand_search_confirmation.result_ready_fact)
    elif case=="missing_blank":state.facts.pop("inspect_context.detail_blank")
    elif case=="conflicting_animation":state=state.model_copy(update={"animation":Observation(observed_at=4.,source="conflicting_positive_evidence")})
    planner=RulePlanner(hand_book());planner.last_completed=rules[1].id
    assert bool(planner.filter_actions(state,[action]))==(case=="allowed_unknown")
    if case!="playing":assert state.animation.value is None


@pytest.mark.parametrize("case",["valid","missing","duplicate","wrong_target"])
def test_hand_ui_policy_requires_exact_three_child_rules(case):
    from master_duel_advisor.ui_policy import UiPolicy,UiRule
    book=hand_book();rules=[r for r in book.rules if r.logical_hand_search_confirmation]
    ui=[UiRule(prompt=r.prompt,type=r.type,source_region=r.source_region,card_id=r.card_id,target=r.target) for r in rules]
    if case=="missing":ui.pop()
    elif case=="duplicate":ui.append(ui[-1])
    elif case=="wrong_target":ui[-1]=ui[-1].model_copy(update={"target":"self.hand.other"})
    if case=="valid":UiPolicy(rules=ui).validate_hands(book)
    else:
        with pytest.raises(ValueError,match="一意UI"):
            UiPolicy(rules=ui).validate_hands(book)
