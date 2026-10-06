"""作業中hand-searchの失敗再現。元画像/原時計は書換えず、UI入力は行いません。

receipt・live_mss wrapper・clock・epochは明示的なsynthetic fixtureです。
画像だけ実資料を使い、これらを実機成功標本や送信証明へ換算しません。
"""
from pathlib import Path

import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.hand_search import HandSearchVision,local_card_rectangle,ready_visible_card
from master_duel_advisor.image_io import read_image

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/dragondark-hand-search-calibration-v3"
BURST=ROOT/"artifacts/baseline-tester/DRAGONDARK_REVEAL_TEMPORAL_TRAIN_v2_20261006/chain-cancel-reveal-continuous"
SYNTHETIC_RECT=(100,200,1380,920)


def vision():return HandSearchVision(BASE/"hand-search.json")


def synthetic_frame(index,at,sequence,epoch=42):
    """合成取得wrapper。元MSSのmetadata/時刻を変更する処理ではありません。"""
    return Frame(read_image(BURST/f"frame-{index:04d}.png"),at,sequence,
        capture_source="live_mss",capture_rect=SYNTHETIC_RECT,input_epoch=epoch)


def synthetic_context():
    return {"action_id":"synthetic-test-episode","hand_search_confirmation":{"card_id":"13906"},
        "steps":[{"input_sent":True,"before_sequence":9,
            "hand_before":{"facts":{"hand_search.layout":{"value":"hand7-slot3"}}}},
            {"input_sent":True,"before_sequence":20,"client_rect":list(SYNTHETIC_RECT),"input_epoch":42}]}


def synthetic_handoff_vision():
    v=vision();v.episode={"action_id":"synthetic-test-episode","layout":"hand7-slot3",
        "profile_sha256":v.sha256,"source_sequence":9,"failed":None,"ready":True,
        "anchor":{"seq":45,"at":9.,"bbox":[582,447,118,174],"cid":"13906"},
        "handoff":{"seq":61,"at":10.,"bbox":[589.3044,595.1580,102.8201,151.5912]},
        "last_seq":61,"last_at":10.,"trace":[],"entered":True,"raised":True}
    return v


@pytest.mark.parametrize("folder,expected_layout",[
    ("DRAGONDARK_SEARCH_TRAIN_v1_20261006/effect-menu-before","hand6-slot3"),
    ("DRAGONDARK_REVEAL_TEMPORAL_TRAIN_v2_20261006/effect-menu-before","hand7-slot3"),
    ("DRAGONDARK_PILOT_PREPARATION_v1_20261006/ready-effect-menu","hand6-slot3")])
def test_source_three_actual_scenes_geometry_detail_and_effect(folder,expected_layout):
    pixels=read_image(ROOT/"artifacts/baseline-tester"/folder/"frame-0000.png")
    result=vision().recognize(Frame(pixels,0,0,capture_source="saved_image"))
    assert result["detail_cid"]=="13906" and result["detail_score"]>=.98
    assert result["source_layout"]==expected_layout
    assert result["source_geometry"][expected_layout] is not None


def test_actual_ready_hand6_visible_card_is_not_rejected_for_cut_fanned_shape():
    pixels=read_image(ROOT/"artifacts/baseline-tester/DRAGONDARK_SEARCH_TRAIN_v1_20261006/post-search-hand-unselected/frame-0000.png")
    # 原hand6に連続handoffは欠測。bboxは明示synthetic局所診断で実追跡証拠ではありません。
    visible=ready_visible_card(pixels,(633,606,100,150))
    assert visible is not None,"隣cardによる遮蔽を全矩形必須条件が取り逃す"
    assert visible["role"]=="handoff_visible_interior"
    x,y,w,h=visible["bbox"];px,py=visible["point"]
    assert x<px<x+w and y<py<y+h<=720


@pytest.mark.parametrize("bbox",[(533,606,100,150),(733,606,100,150),(633,540,100,150)])
def test_ready_visible_card_rejects_wrong_handoff_neighbor_and_background(bbox):
    pixels=read_image(ROOT/"artifacts/baseline-tester/DRAGONDARK_SEARCH_TRAIN_v1_20261006/post-search-hand-unselected/frame-0000.png")
    # 合成handoffは対象Dark以外の位置/背景。元画像/metadataは不変です。
    assert ready_visible_card(pixels,bbox) is None


def test_actual_unselected_hand6_background_line_is_not_selected_card_top():
    pixels=read_image(ROOT/"artifacts/baseline-tester/DRAGONDARK_SEARCH_TRAIN_v1_20261006/post-search-hand-unselected/frame-0000.png")
    rectangle=local_card_rectangle(pixels,(604,527,155,180),(527,580),682)
    assert rectangle is None,"unselected画面の背景横線をselected上辺として採用している"


def test_actual_hand7_selected_card_has_connected_rectangle():
    pixels=read_image(ROOT/"artifacts/baseline-tester/DRAGONDARK_REVEAL_TEMPORAL_TRAIN_v2_20261006/post-reveal-fresh-hand-inspect/frame-0000.png")
    assert local_card_rectangle(pixels,(562,527,155,180),(527,580),640) is not None


@pytest.mark.parametrize("case",["fresh","expired_handoff","same_sequence","older_sequence","epoch_changed"])
def test_handoff_rechecks_deadline_epoch_and_sequence(case):
    v=synthetic_handoff_vision();context=synthetic_context();at=10.1;seq=62;epoch=42
    if case=="expired_handoff":at=14.
    elif case=="same_sequence":seq=61
    elif case=="older_sequence":seq=60
    elif case=="epoch_changed":epoch=43
    frame=synthetic_frame(41,at,seq,epoch);result=v.observe(frame,context,v.recognize(frame))
    if case=="fresh":assert result["ready"] and not result["failed"]
    else:assert result["failed"] and not result["ready"],case+"をhandoff後early returnが検査していない"


@pytest.mark.parametrize("gap,allowed",[(.299,True),(.300,True),(.301,False)])
def test_public_anchor_tracking_300ms_gap_boundary(gap,allowed):
    v=vision();context=synthetic_context();first=synthetic_frame(25,1.,45)
    initial=v.observe(first,context,v.recognize(first))
    assert initial["anchor"] is not None
    current=synthetic_frame(26,1.+gap,46)
    result=v.observe(current,context,v.recognize(current))
    assert (result["failed"] is None)==allowed


def test_anchor_missing_does_not_construct_handoff_from_hand_pixels():
    v=vision();frame=synthetic_frame(41,10.,61)
    result=v.observe(frame,synthetic_context(),v.recognize(frame))
    assert result["anchor"] is None and result["handoff"] is None and not result["ready"]


@pytest.mark.parametrize("case",["safe_point","different_point","different_bbox","old_geometry",
    "parent_missing","other_episode","cancel_not_sent","wrong_cancel_region"])
def test_ready_visible_safe_point_is_used_by_action_proof_and_coordinate_guard(tmp_path,case):
    """合成receipt/clockで局所API→proof→座標validatorだけ接続。入力は実行しません。"""
    from types import SimpleNamespace
    from test_agent_loop import setup
    from master_duel_advisor.models import GameState,Observation
    from master_duel_advisor.perception import Perception
    from master_duel_advisor.regions import Region,Rect
    from master_duel_advisor.strategy_rules import LogicalHandSearchConfirmation

    v=synthetic_handoff_vision();goal=LogicalHandSearchConfirmation()
    context=synthetic_context();context["hand_search_confirmation"]=goal.model_dump(mode="json")
    frame=synthetic_frame(41,10.1,62)
    perception=object.__new__(Perception)
    perception.hand_vision=v;perception.hand_goal=goal;perception.hand_context=None
    perception.inspect_client_rect=SYNTHETIC_RECT
    observed={"fact.inspect_context.main1":Observation(value="true",confidence=1,observed_at=10.1),
        "fact.inspect_context.detail_blank":Observation(value="true",confidence=1,observed_at=10.1,source="template:synthetic")}
    actions=[]
    perception._hand_search_observations(frame,observed,actions,{},context)
    action=next(a for a in actions if a.type.value=="SELECT_CARD")
    visible=v.episode["current_ready_geometry"]
    assert action.hand_search_proof.point==tuple(visible["point"])
    assert action.hand_search_proof.evidence_bbox==tuple(visible["bbox"])

    loop,clicker,_=setup(tmp_path)
    loop.pipeline.perception=SimpleNamespace(hand_goal=goal,hand_vision=v,response_goals=())
    loop.inspection_goal=None;loop.inspection_live_bound=True;loop.screen_rect=SYNTHETIC_RECT
    loop.clock=lambda:10.1
    loop.telemetry.active={"action_id":v.episode["action_id"],"hand_search_confirmation":goal.model_dump(mode="json"),
        "steps":[{"input_sent":True,"input_epoch_verified":True,"result":"changed","action":{"type":"ACTIVATE","source_region":goal.activate_region}},
            {"input_sent":True,"input_epoch_verified":True,"result":"changed","input_epoch":42,
             "action":{"type":"CANCEL","source_region":goal.cancel_region}},{}]}
    loop.calibration.regions[goal.inspect_region]=Region(rect=Rect(x=.4,y=.4,width=.2,height=.2),kind="action")
    proof=action.hand_search_proof
    if case=="different_point":
        proof=proof.model_copy(update={"point":(proof.point[0]+1,proof.point[1])})
    elif case=="different_bbox":
        x,y,w,h=proof.evidence_bbox;proof=proof.model_copy(update={"evidence_bbox":(x+1,y,w,h)})
    elif case=="old_geometry":v.episode["last_seq"]-=1
    elif case=="parent_missing":loop.telemetry.active=None
    elif case=="other_episode":loop.telemetry.active["action_id"]="other-episode"
    elif case=="cancel_not_sent":loop.telemetry.active["steps"][1]["input_sent"]=None
    elif case=="wrong_cancel_region":loop.telemetry.active["steps"][1]["action"]["source_region"]="action.unknown"
    action=action.model_copy(update={"hand_search_proof":proof})
    state=GameState(sequence=62,captured_at=10.1)
    if case=="safe_point":
        assert loop._coordinates(action,frame.pixels.shape,frame=frame,state=state)==(
            SYNTHETIC_RECT[0]+visible["point"][0],SYNTHETIC_RECT[1]+visible["point"][1])
    else:
        message="親/Cancel" if case in {"parent_missing","other_episode","cancel_not_sent","wrong_cancel_region"} else "可視安全点"
        with pytest.raises(ValueError,match=message):
            loop._coordinates(action,frame.pixels.shape,frame=frame,state=state)
    assert clicker.points==[]
