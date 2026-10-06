"""detail artの方式選択資料と合成negative。元画像/原時計/UIは変更しません。"""
import json
from pathlib import Path
import shutil

import numpy as np
import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.hand_search import HandSearchVision
from master_duel_advisor.image_io import read_image

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/dragondark-hand-search-calibration-v3"
DATA=ROOT/"artifacts/baseline-tester"
MODE="rgb_or_native_art_sift_v1"
PARAMETERS={"art_inside_thumbnail":[12,30,78,72],"SIFT_nfeatures":200,"footprint_radius_factor":5.31,
    "support_boundary_tolerance_px":1e-12,
    "mutual_lowe":.75,"ransac_px":2.,"minimum_inliers":6,"minimum_ratio":.7,
    "scale":[.9,1.1],"shift_px":3,"art_spread":[39,36]}


@pytest.fixture
def vision(tmp_path):
    copy=tmp_path/"profile";shutil.copytree(BASE,copy)
    path=copy/"hand-search.json";config=json.loads(path.read_text(encoding="utf-8"))
    config.update(detail_recognition_mode=MODE,detail_art_parameters=PARAMETERS)
    path.write_text(json.dumps(config),encoding="utf-8")
    return HandSearchVision(path)


@pytest.mark.parametrize("index",range(10))
def test_new_temporal_detail_color_variation_requires_art_identity(vision,index):
    image=read_image(DATA/"DRAGONDARK_SOURCE_TEMPORAL_FIXED_v1_20261006/menu"/f"frame-{index:04d}.png")
    result=vision.recognize(Frame(image,0,index,capture_source="saved_image"))
    assert result["detail_score"]<.98  # 既知失敗のRGB値は下げません。
    assert result["detail_cid"]=="13906"
    assert result["detail_recognition"]=="native_art_sift"


@pytest.mark.parametrize("folder",["CARD_NAME_OCR_EXPLORATION_20261006/ash-first",
    "CARD_NAME_OCR_EXPLORATION_20261006/driver-first","MAXXC_MENU_TRAIN_v1_full",
    "MAXXC_CURRENT_HAND_TRAIN_20261006/solar-menu"])
def test_wrong_cids_are_rejected_by_both_rgb_and_art_branches(vision,folder):
    folder=DATA/folder;manifest=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
    for item in manifest["frames"]:
        result=vision.recognize(Frame(read_image(folder/item["file"]),0,0,capture_source="saved_image"))
        assert result["detail_score"]<.98
        assert result["detail_cid"] is None
        assert not result["detail_art"]["accepted"]


def test_legacy_reference_still_uses_rgb_and_known_low_spread_stays_unknown(vision):
    image=read_image(DATA/"DRAGONDARK_SEARCH_TRAIN_v1_20261006/effect-menu-before/frame-0000.png")
    result=vision.recognize(Frame(image,0,0,capture_source="saved_image"))
    assert result["detail_score"]>=.98 and result["detail_recognition"]=="rgb"
    image=read_image(DATA/"DRAGONDARK_SEARCH_TRAIN_v1_20261006/effect-menu-before/frame-0004.png")
    result=vision.recognize(Frame(image,0,0,capture_source="saved_image"))
    assert result["detail_cid"] is None and not result["detail_art"]["accepted"]


@pytest.mark.parametrize("case",["blank","common_frame_only","few_features"])
def test_synthetic_blank_common_frame_and_few_art_features_are_unknown(vision,case):
    image=np.zeros((720,1280,3),np.uint8)
    if case=="common_frame_only":
        # synthetic: 既知cardの共通枠だけ。実イラストを白へ置換、元assetは不変。
        reference=read_image(vision.asset(vision.config["detail_references"][0])).copy()
        reference[30:102,12:90]=255;image[151:301,27:130]=reference
    elif case=="few_features":
        image[151:301,27:130]=255
        image[210:212,75:77]=0
    result=vision.recognize(Frame(image,0,0,capture_source="saved_image"))
    assert result["detail_cid"] is None and not result["detail_art"]["accepted"]


def test_art_method_and_reference_hashes_are_in_provenance(vision):
    provenance=vision.provenance()["detail_recognition"]
    assert provenance["mode"]==MODE and provenance["parameters"]==PARAMETERS
    assert provenance["reference_hashes"]==[r["sha256"] for r in vision.config["detail_references"]]


@pytest.mark.parametrize("side",["left","right","top","bottom"])
@pytest.mark.parametrize("delta,accepted",[(0.,True),(-.000001,False)])
def test_synthetic_descriptor_support_exact_boundary_and_tiny_crossing(side,delta,accepted):
    from types import SimpleNamespace
    from master_duel_advisor.hand_search import art_keypoint_inside
    radius=5.31*2;x=39.;y=36.
    if side=="left":x=radius+delta
    elif side=="right":x=77-radius-delta
    elif side=="top":y=radius+delta
    else:y=71-radius-delta
    assert art_keypoint_inside(SimpleNamespace(pt=(x,y),size=2.))==accepted


def test_reference_and_candidate_absent_art_descriptors_fail_closed():
    from master_duel_advisor.hand_search import NativeArtDetails
    blank=np.zeros((150,103,3),np.uint8);matcher=NativeArtDetails([blank,blank])
    points,descriptors=matcher.references[0]
    assert len(points)==0 and descriptors is None
    assert not matcher.recognize(blank)["accepted"]
