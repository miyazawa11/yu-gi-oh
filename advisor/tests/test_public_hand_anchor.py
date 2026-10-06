"""既知方法選択資料の公開face再生。receiptはsynthetic、原時計/hashと画像を保持。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.hand_search import HandSearchVision
from master_duel_advisor.hand_search import PublicHandArt
from master_duel_advisor.image_io import read_image

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/dragondark-hand-search-calibration-v4"
DATA=ROOT/"artifacts/baseline-tester"
BURST=DATA/"DRAGONDARK_HAND6_CHAIN_REVEAL_TRAIN_v3_20261006/chain-cancel-reveal-continuous"
MODE="native_public_art_common_support_v1"
PARAMETERS={"roi":[500,400,330,236],"candidate_features":800,"ratio":.75,"inliers":6,"inlier_ratio":.7,
    "spread":[39,36],"scale":[.9,1.25],"rotation_abs":3,"fullface_width":[100,130],"fullface_height":[145,190],
    "edge_support_min":.35,"edge_strip_radius":2,"probe_models":2,"common_scene_support":6,
    "common_ref_spread":[39,36],"common_scene_residual_px":2.,"descriptor_radius_factor":5.31,
    "support_boundary_tolerance_px":1e-12}


@pytest.fixture
def vision(tmp_path):
    output=tmp_path/"profile";shutil.copytree(BASE,output)
    path=output/"hand-search.json";config=json.loads(path.read_text(encoding="utf-8"))
    config.update(public_anchor_mode=MODE,public_art_parameters=PARAMETERS)
    path.write_text(json.dumps(config),encoding="utf-8")
    return HandSearchVision(path)


def frames(start=151,end=315):
    manifest=json.loads((BURST/"manifest.json").read_text(encoding="utf-8"))
    for item in manifest["frames"]:
        if start<=item["capture_sequence"]<=end:
            path=BURST/item["file"]
            assert hashlib.sha256(path.read_bytes()).hexdigest()==item["sha256"]
            yield Frame(read_image(path),item["captured_at_monotonic"],item["capture_sequence"],
                capture_source="live_mss",capture_rect=tuple(item["rect_before"]),input_epoch=97996062)


def synthetic_context():
    return {"action_id":"synthetic-public-stage-replay","hand_search_confirmation":{"card_id":"13906"},
        "steps":[{"input_sent":True,"before_sequence":0,"hand_before":{"facts":{"hand_search.layout":{"value":"hand6-slot3"}}}},
            {"input_sent":True,"before_sequence":150,"client_rect":[-1918,817,-638,1537],"input_epoch":97996062}]}


def test_public_art_new_mode_uses_existing_refs_and_full_scene_search_without_ncc_oracle(vision):
    assert vision.public_mode==MODE
    frame=next(frames(159,159));result=vision.public_art.recognize(frame.pixels)
    assert result["accepted"] and not result["ambiguous"] and result["representative"]
    assert all(r["inliers"]>=6 for r in result["primary"] if r["accepted"])
    assert vision.provenance()["public_anchor"]["mode"]==MODE


def test_original_order_replay_reaches_handoff_and_ready_without_reanchor(vision):
    context=synthetic_context();observed=[]
    for frame in frames(151,191):
        ep=vision.observe(frame,context,vision.recognize(frame));observed.append(deepcopy(ep))
        assert ep is not None and ep["failed"] is None
    assert ep["anchor"]["seq"]==158 and ep["handoff"]["seq"]==179
    assert ep["ready"] and ep["current_ready_geometry"]["role"]=="handoff_visible_interior"
    assert sum(bool(r.get("pre_entry_upward_exception")) for r in ep["trace"])==1
    assert {r["anchor"]["seq"] for r in observed if r["anchor"]}=={158}


@pytest.mark.parametrize("group",["DRAGONDARK_SEARCH_TRAIN_v1_20261006/post-search-hand-inspected",
    "DRAGONDARK_SEARCH_TRAIN_v1_20261006/post-search-hand-unselected",
    "DRAGON_NEIGHBOR_DETAIL_TRAIN_v1_20261006/roar-detail-negative",
    "DRAGON_NEIGHBOR_DETAIL_TRAIN_v1_20261006/thunderstormech-detail-negative"])
def test_static_same_dark_and_neighbor_detail_are_not_public_face_anchor(vision,group):
    result=vision.public_art.recognize(read_image(DATA/group/"frame-0000.png"))
    assert not result["accepted"]


@pytest.mark.parametrize("case",["entered","outside_point","outside_flowbox","multiple_instance"])
def test_pre_entry_exception_requires_current_unique_face_and_containment(vision,case,monkeypatch):
    frame=next(frames(159,159));face=vision.public_art.recognize(frame.pixels)["representative"]
    l,t,w,h=face["bbox"];box=np.float32([[l,t],[l+w,t],[l+w,t+h],[l,t+h]])
    points=np.float32([[l+w*(.35+i*.04),t+h*.5] for i in range(6)])
    episode={"entered":False,"anchor":{"cid":"13906"}}
    assert vision.pre_entry_upward_supported(episode,frame,points,box)["permitted"]
    if case=="entered":episode["entered"]=True
    elif case=="outside_point":points[0]=[0,0]
    elif case=="outside_flowbox":box[0]=[0,0]
    elif case=="multiple_instance":monkeypatch.setattr(vision.public_art,"recognize",lambda pixels:{"accepted":False,"ambiguous":True,"representative":face})
    assert not vision.pre_entry_upward_supported(episode,frame,points,box)["permitted"]


def supported_synthetic_model(vision,shift=0,ids_offset=0,ref=0):
    """合成対応点＋合成edge支持。実image識別精度とは区別します。"""
    original=np.float32([[18,36],[75,36],[18,94],[75,94],[45,36],[45,94],[18,65],[75,65]])
    current=original*1.1+np.float32([630+shift,447])
    sizes=np.ones(len(original),np.float32)*.5
    row,_=vision.public_art.model(original,current,sizes,current,np.ones((720,1280),np.uint8)*255)
    row["reference_index"]=ref
    row["candidate_ids"]=[x+ids_offset for x in row["candidate_ids"]]
    assert row["accepted"] and row["inliers"]>=6 and all(np.array(row["spread"])>=[39,36])
    return row


def test_two_individually_supported_instances_are_ambiguous_even_if_probe_is_weaker(vision):
    first=supported_synthetic_model(vision)
    second=supported_synthetic_model(vision,shift=60,ids_offset=100,ref=1)
    # 同品質の少数model。対応spreadを残す6点を選びます。
    for key in ["candidate_ids","reference_support_points","scene_support_points"]:second[key]=second[key][:6]
    second["inliers"]=6
    assert PublicHandArt.resolve_models([first],[])["accepted"]
    assert PublicHandArt.resolve_models([second],[])["accepted"]
    result=PublicHandArt.resolve_models([first],[second])
    assert result["ambiguous"] and not result["accepted"] and result["representative"] is None


def test_same_scene_support_allows_different_projected_origins_not_distance_merge(vision):
    first=supported_synthetic_model(vision)
    original=np.array(first["reference_support_points"],np.float32)+[4,0]
    current=np.array(first["scene_support_points"],np.float32)
    second,_=vision.public_art.model(original.astype(np.float32),current,np.ones(len(current),np.float32)*.5,
        current,np.ones((720,1280),np.uint8)*255)
    second["reference_index"]=1
    assert second["accepted"] and np.linalg.norm(np.array(first["bbox"][:2])-second["bbox"][:2])>3
    assert PublicHandArt.compatible(first,second)
    assert PublicHandArt.resolve_models([first,second],[])["accepted"]


def test_all_pair_rejects_single_link_and_probe_only_never_becomes_primary(vision):
    first=supported_synthetic_model(vision)
    middle=deepcopy(first);last=deepcopy(first)
    # 共通scene IDsの構成だけを合成。A-BとB-Cは成立してもA-Cの共通は4点。
    middle["candidate_ids"]=[0,1,2,3,4,5,100,101]
    last["candidate_ids"]=[0,1,2,3,100,101,102,103]
    # ref/scene対応をindex別に同じ座標へ揃え、個々のqualityは前提として固定。
    base={i:(first["reference_support_points"][i],first["scene_support_points"][i]) for i in range(8)}
    base.update({100:base[6],101:base[7],102:base[4],103:base[5]})
    for row in [middle,last]:
        row["reference_support_points"]=[base[i][0] for i in row["candidate_ids"]]
        row["scene_support_points"]=[base[i][1] for i in row["candidate_ids"]]
    assert PublicHandArt.compatible(first,middle) and PublicHandArt.compatible(middle,last)
    assert not PublicHandArt.compatible(first,last)
    assert PublicHandArt.resolve_models([first,middle],[last])["ambiguous"]
    assert not PublicHandArt.resolve_models([],[first])["accepted"]


def test_old_ncc_profile_keeps_old_anchor_and_new_mode_never_falls_back_to_it(vision,monkeypatch):
    old=HandSearchVision(BASE/"hand-search.json")
    folder=DATA/"DRAGONDARK_REVEAL_TEMPORAL_TRAIN_v2_20261006/chain-cancel-reveal-continuous"
    item=next(r for r in json.loads((folder/"manifest.json").read_text(encoding="utf-8"))["frames"] if r["capture_sequence"]==45)
    frame=Frame(read_image(folder/item["file"]),item["captured_at_monotonic"],45,
        capture_source="live_mss",capture_rect=(-1918,817,-638,1537),input_epoch=97996062)
    context=synthetic_context();context["steps"][-1]["before_sequence"]=40
    ep=old.observe(frame,context,old.recognize(frame))
    assert old.public_mode=="gray_ncc_v1" and ep["anchor"] and ep["anchor"]["score"]>=.98
    monkeypatch.setattr(vision.public_art,"recognize",lambda pixels:{"accepted":True,"ambiguous":True,"representative":None})
    new=vision.observe(frame,context,vision.recognize(frame))
    assert new["anchor"] is None


@pytest.mark.parametrize("case",["epoch","sequence","gap","own_chain","GY","closed_no_context"])
def test_scope_order_and_pause_boundaries_preserve_existing_guards(vision,case):
    from dataclasses import replace
    first,last=list(frames(158,159));context=synthetic_context()
    ep=vision.observe(first,context,vision.recognize(first));assert ep["anchor"]
    static=vision.recognize(last)
    if case=="epoch":last=replace(last,input_epoch=97996063)
    elif case=="sequence":last=replace(last,sequence=first.sequence)
    elif case=="gap":last=replace(last,captured_at=first.captured_at+.301)
    elif case=="own_chain":static["own_chain"]=True
    elif case=="GY":static["gy_panel"]=True
    elif case=="closed_no_context":context=None
    result=vision.observe(last,context,static)
    if case=="closed_no_context":assert result is None
    elif case in {"own_chain","GY"}:assert not result["trace"] and result["handoff"] is None
    else:assert result["failed"] and result["handoff"] is None


def test_model_parameters_are_declared_and_unknown_mode_or_changed_quality_is_rejected(tmp_path):
    for index,extra in enumerate([{"public_anchor_mode":"unknown"},{"public_anchor_mode":MODE,"public_art_parameters":{**PARAMETERS,"ratio":.5}}]):
        output=tmp_path/f"profile{index}";shutil.copytree(BASE,output);path=output/"hand-search.json"
        config=json.loads(path.read_text(encoding="utf-8"));config.update(extra)
        path.write_text(json.dumps(config),encoding="utf-8")
        with pytest.raises(ValueError,match="public"):HandSearchVision(path)


def test_original_clock_handoff_expires_and_failed_episode_does_not_reanchor(vision):
    context=synthetic_context();failure=None
    for frame in frames(151,220):
        ep=vision.observe(frame,context,vision.recognize(frame))
        if ep["failed"]:
            failure=(frame,deepcopy(ep));break
    assert failure is not None and failure[0].sequence==219
    assert failure[1]["failed"]=="expired_handoff"
    next_frame=next(frames(220,220))
    result=vision.observe(next_frame,context,vision.recognize(next_frame))
    assert result["failed"]=="expired_handoff" and result["anchor"]["seq"]==158


@pytest.mark.parametrize("conflict",[None,"opponent","DRAW"])
def test_ready_window_uses_current_main1_and_safe_geometry_through_pipeline(vision,conflict):
    """原時間系列と合成receipt/判断clock。入力は呼ばず可視候補窓だけを検査。"""
    from master_duel_advisor.cli import build_pipeline,close_pipeline
    from master_duel_advisor.models import Observation
    p=build_pipeline(BASE/"calibration.json",ROOT/"data/decks/thunder-dragon-review/cards.sqlite3",BASE/"solo-route.json",BASE/"ui-rules.json")
    try:
        p.perception.configure_hand_search(p.perception.hand_goal,vision.path.parent)
        p.perception.inspect_client_rect=(-1918,817,-638,1537)
        context=synthetic_context();context["hand_search_confirmation"]=p.perception.hand_goal.model_dump(mode="json")
        for frame in frames(151,191):state=p.perception.process(frame,hand_episode_context=context)
        ep=p.perception.hand_episode
        assert ep["anchor"]["seq"]==158 and ep["handoff"]["seq"]==179 and ep["ready"]
        goal=p.perception.hand_goal
        action=next(a for a in state.visible_actions if a.source_region==goal.inspect_region)
        assert list(action.hand_search_proof.point)==ep["current_ready_geometry"]["point"]
        assert list(action.hand_search_proof.evidence_bbox)==ep["current_ready_geometry"]["bbox"]
        assert state.animation.value is None
        if conflict:
            field="turn_player" if conflict=="opponent" else "phase"
            state=state.model_copy(update={field:Observation(value=conflict,confidence=1,observed_at=frame.captured_at,source="synthetic-positive-conflict")})
        p.planner.last_completed=next(r.id for r in p.planner.book.rules if r.source_region==goal.cancel_region)
        p.clock=lambda:frame.captured_at+.01;generate=p.rules.generate
        p.rules.generate=lambda s,now:generate(s,frame.captured_at+.01)
        result=p.process(frame,observed_state=state)
        assert bool(result["recommendation"]["action"])==(conflict is None)
        if conflict is None:assert result["recommendation"]["action"]["source_region"]==goal.inspect_region
    finally:close_pipeline(p)
