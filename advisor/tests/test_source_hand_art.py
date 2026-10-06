"""現在detail→選択hand art所属の合成/既知資料。実入力は行いません。"""
import json
from pathlib import Path
import shutil

import numpy as np
import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.hand_search import HandSearchVision,DETAIL_ART_MODE,DETAIL_ART_PARAMETERS
from master_duel_advisor.image_io import read_image

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/dragondark-hand-search-calibration-v3"
DATA=ROOT/"artifacts/baseline-tester"
SOURCE_MODE="detail_to_selected_hand_art_v1"
PARAMETERS={"candidate_roi":[-78,536,155,184],"candidate_nfeatures":300,"forward_lowe":.75,"ransac_px":2.,
    "minimum_inliers":6,"minimum_ratio":.7,"spread":[39,36],"scale":[.9,1.1],"rotation_degrees":3,
    "effect_to_art_top":[58,74],"art_center_to_effect_x":20,"same_position_merge_px":3,
    "max_probe_models_per_reference":2,"descriptor_radius_factor":5.31,"support_boundary_tolerance_px":1e-12}


@pytest.fixture
def vision(tmp_path):
    copy=tmp_path/"profile";shutil.copytree(BASE,copy);path=copy/"hand-search.json"
    config=json.loads(path.read_text(encoding="utf-8"))
    config.update(detail_recognition_mode=DETAIL_ART_MODE,detail_art_parameters=DETAIL_ART_PARAMETERS,
        source_art_mode=SOURCE_MODE,source_art_parameters=PARAMETERS)
    path.write_text(json.dumps(config),encoding="utf-8")
    return HandSearchVision(path)


@pytest.mark.parametrize("index",range(10))
def test_new_source_requires_same_frame_detail_effect_and_unique_art_pose(vision,index):
    pixels=read_image(DATA/"DRAGONDARK_SOURCE_TEMPORAL_FIXED_v1_20261006/menu"/f"frame-{index:04d}.png")
    result=vision.recognize(Frame(pixels,0,index,capture_source="saved_image"))
    assert result["source_layout"]=="hand6-slot3"
    pose=result["source_art_pose"]["hand6-slot3"]
    assert pose["accepted"] and pose["frame_seq"]==index and pose["observed_at"]==0
    assert pose["detail_cid"]=="13906" and pose["art_bbox"]
    assert pose["reference_hashes"]==[r["sha256"] for r in vision.config["detail_references"]]
    # artをfull-cardへ偽変換せず、legacy Hough診断を残します。
    assert "bbox" not in pose


def test_selected7_art_belongs_to_hand_but_without_effect_produces_no_source(vision):
    pixels=read_image(DATA/"DRAGONDARK_REVEAL_TEMPORAL_TRAIN_v2_20261006/post-reveal-fresh-hand-inspect/frame-0000.png")
    pose=vision.source_art.recognize(pixels,[640,522])
    assert pose["accepted"]
    result=vision.recognize(Frame(pixels,0,0,capture_source="saved_image"))
    assert result["source_layout"] is None
    assert result["source_art_pose"]["hand7-slot3"]["status"]=="not_applicable"


@pytest.mark.parametrize("group",["roar-detail-negative","thunderstormech-detail-negative"])
def test_actual_neighbor_cids_do_not_run_source_pose_or_create_source(vision,group):
    folder=DATA/"DRAGON_NEIGHBOR_DETAIL_TRAIN_v1_20261006"/group
    for item in json.loads((folder/"manifest.json").read_text(encoding="utf-8"))["frames"]:
        result=vision.recognize(Frame(read_image(folder/item["file"]),0,0,capture_source="saved_image"))
        assert result["detail_cid"] is None and result["source_layout"] is None
        assert all(p["status"]=="not_applicable" and p["accepted"] is None for p in result["source_art_pose"].values())


def test_same_dark_unselected_card_art_is_not_selected_source(vision):
    pixels=read_image(DATA/"DRAGONDARK_SEARCH_TRAIN_v1_20261006/post-search-hand-unselected/frame-0000.png")
    pose=vision.source_art.recognize(pixels,[683,524])
    assert not pose["accepted"]


def test_synthetic_clear_and_weak_second_model_both_pass_alone_but_are_ambiguous(vision):
    # 実refの対応点だけを合成移動。実pixel抽出の精度とは扱いません。
    points,_=vision.source_art.references[0]
    weak=np.unique(np.r_[np.linspace(0,len(points)-1,12,dtype=int),np.argmin(points,axis=0),np.argmax(points,axis=0)])
    a=np.vstack([points,points[weak]])
    b=np.vstack([points*1.065+[627.4,558.0],points[weak]*1.065+[635.4,560.0]]).astype(np.float32)
    sizes=np.ones(len(a),np.float32)
    alone,_=vision.source_art.model(points,b[:len(points)],sizes[:len(points)],[683,524])
    first,keep=vision.source_art.model(a,b,sizes,[683,524])
    second,_=vision.source_art.model(a[~keep],b[~keep],sizes[~keep],[683,524])
    assert alone["accepted"] and first["accepted"] and second["accepted"]
    assert vision.source_art.different([first,second])


def test_ambiguous_runtime_pose_never_uses_positive_legacy_geometry(vision,monkeypatch):
    pixels=read_image(DATA/"DRAGONDARK_PILOT_PREPARATION_v1_20261006/ready-effect-menu/frame-0000.png")
    legacy=HandSearchVision(BASE/"hand-search.json").recognize(Frame(pixels,0,0,capture_source="saved_image"))
    assert legacy["source_geometry"]["hand6-slot3"] is not None
    # synthetic矛盾結果。境界側もambiguityを明示拒否しacceptedだけを信用しません。
    monkeypatch.setattr(vision.source_art,"recognize",lambda *args:{"status":"ambiguous","accepted":True,"ambiguous":True,"art_bbox":[640,590,83,77]})
    result=vision.recognize(Frame(pixels,0,0,capture_source="saved_image"))
    assert result["source_layout"] is None and result["source_geometry"]["hand6-slot3"] is None


@pytest.mark.parametrize("case",["GY","main1_unknown"])
def test_calibrated_perception_and_strict_filter_abstain_for_wrong_context(vision,monkeypatch,case):
    from master_duel_advisor.cli import build_pipeline,close_pipeline
    # 元calのsibling registry pathを壊すprofile移動をせず、hand configだけ新modeを結線。
    p=build_pipeline(BASE/"calibration.json",ROOT/"data/decks/thunder-dragon-review/cards.sqlite3",BASE/"solo-route.json",BASE/"ui-rules.json")
    try:
        p.perception.configure_hand_search(p.perception.hand_goal,vision.path.parent)
        if case=="GY":
            original=p.perception.hand_vision.recognize
            def gy(frame):
                value=original(frame);value["gy_panel"]=True;return value
            monkeypatch.setattr(p.perception.hand_vision,"recognize",gy)
        else:
            monkeypatch.setattr(p.perception.matchers["fact.inspect_context.main1"],"match",lambda *args:(None,0))
        pixels=read_image(DATA/"DRAGONDARK_PILOT_PREPARATION_v1_20261006/ready-effect-menu/frame-0000.png")
        state=p.perception.process(Frame(pixels,0,0,capture_source="saved_image"))
        assert not any(a.source_region==p.perception.hand_goal.activate_region for a in state.visible_actions)
        assert not any(a.source_region==p.perception.hand_goal.activate_region for a in p.planner.filter_actions(state,state.visible_actions))
    finally:close_pipeline(p)


@pytest.mark.parametrize("case",["wrong_mode","changed_params"])
def test_source_art_mode_or_parameters_cannot_silently_change(vision,case):
    config=json.loads(vision.path.read_text(encoding="utf-8"))
    if case=="wrong_mode":config["source_art_mode"]="unverified_source_mode"
    else:config["source_art_parameters"]["minimum_ratio"]=.5
    vision.path.write_text(json.dumps(config),encoding="utf-8")
    with pytest.raises(ValueError,match="source"):
        HandSearchVision(vision.path)


def test_probe_only_models_cannot_create_positive_source(vision,monkeypatch):
    pixels=read_image(DATA/"DRAGONDARK_PILOT_PREPARATION_v1_20261006/ready-effect-menu/frame-0000.png")
    monkeypatch.setattr(vision.source_art,"recognize",lambda *args:{"status":"unconfirmed","accepted":False,"primary":[],
        "ambiguity_models":[{"accepted":True,"art_bbox":[640,590,83,77]}],"ambiguous":False,"art_bbox":None})
    assert vision.recognize(Frame(pixels,0,0,capture_source="saved_image"))["source_layout"] is None


def test_two_source_layouts_matching_same_frame_are_unknown(vision,monkeypatch):
    pixels=read_image(DATA/"DRAGONDARK_PILOT_PREPARATION_v1_20261006/ready-effect-menu/frame-0000.png")
    original=vision.scene_scores
    def both(image):
        scores=original(image);scores["effect_hand6-slot3"]=scores["effect_hand7-slot3"]=1.;return scores
    monkeypatch.setattr(vision,"scene_scores",both)
    monkeypatch.setattr(vision.source_art,"recognize",lambda *args:{"status":"supported","accepted":True,"ambiguous":False,"art_bbox":[640,590,83,77]})
    assert vision.recognize(Frame(pixels,0,0,capture_source="saved_image"))["source_layout"] is None


def test_stale_main1_cannot_generate_source_action(vision):
    from master_duel_advisor.perception import Perception
    from master_duel_advisor.models import Observation
    from master_duel_advisor.strategy_rules import LogicalHandSearchConfirmation
    p=object.__new__(Perception);p.hand_vision=vision;p.hand_goal=LogicalHandSearchConfirmation();p.hand_context=None;p.inspect_client_rect=None
    pixels=read_image(DATA/"DRAGONDARK_PILOT_PREPARATION_v1_20261006/ready-effect-menu/frame-0000.png")
    # synthetic時計1→2の古い観測。元MSS時計を変更したfixtureではありません。
    observed={"fact.inspect_context.main1":Observation(value="true",confidence=1,observed_at=1)};actions=[]
    p._hand_search_observations(Frame(pixels,2,0,capture_source="saved_image"),observed,actions,{},None)
    assert actions==[]
