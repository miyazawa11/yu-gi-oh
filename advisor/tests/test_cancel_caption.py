"""新文字尺度/取得由来/原画欠測/出力衝突。合成と既知診断を実機成功に数えません。"""
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pytest

from master_duel_advisor.cancel_caption import CancelCaptionDetector, diagnostic_output_path, tolerant_shape_score, yellow_shape
from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import build_pipeline,close_pipeline
from master_duel_advisor.image_io import read_image
from master_duel_advisor.models import Observation

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/solo-basic-calibration-v3"
TRAIN=ROOT/"artifacts/baseline-tester/OPTIONAL_RESPONSE_TRAIN_v1_20261006"
KNOWN=ROOT/"artifacts/baseline-tester/SOLO_END_FIXED_TEMPORAL_v1_20261006/end"


def available_training():
    rows=[];missing=[]
    for folder in sorted(p for p in TRAIN.iterdir() if p.is_dir()):
        manifest=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
        for item in manifest["frames"]:
            path=folder/item["file"]
            if hashlib.sha256(path.read_bytes()).hexdigest()!=item["sha256"]:
                missing.append(path);continue
            rows.append((folder.name,path))
    return rows,missing


def test_original_training_integrity_failure_is_visible_and_not_82_reproduction():
    rows,missing=available_training()
    assert len(rows)==81 and missing==[TRAIN/"end-response-before/frame-0009.png"]
    incident=json.loads((ROOT/"evaluation/solo-cancel-training-input-incident-v1.json").read_text(encoding="utf-8"))
    assert not incident["training_current_manifest_integrity"]
    assert incident["original_png_missing"] and not incident["replacement_with_other_image"]


@pytest.mark.parametrize("case",["outside","input_collision","existing","valid"])
def test_diagnostic_output_guard_rejects_collisions_before_writing(tmp_path,case):
    evaluation=tmp_path/"evaluation";evaluation.mkdir();input_path=evaluation/"input.json"
    target=evaluation/"new.json";inputs=[input_path]
    if case=="outside":target=tmp_path/"outside.json"
    elif case=="input_collision":target=input_path
    elif case=="existing":target.write_text("preserve",encoding="utf-8")
    if case=="valid":assert diagnostic_output_path(target,inputs,evaluation)==target.resolve()
    else:
        with pytest.raises(ValueError):diagnostic_output_path(target,inputs,evaluation)
    if case=="existing":assert target.read_text(encoding="utf-8")=="preserve"
    else:assert not target.exists()


def test_native_shape_known_classes_and_new_method_selection_images():
    detector=CancelCaptionDetector(BASE/"cancel-caption.json")
    rows,missing=available_training();positive=negative=0
    for cls,path in rows:
        result=detector.detect(read_image(path))
        if cls=="end-response-after":assert not result.passed;negative+=1
        else:assert result.passed;positive+=1
    assert (positive,negative,len(missing))==(61,20,1)
    for path in KNOWN.glob("frame-*.png"):
        result=detector.detect(read_image(path))
        assert result.passed and .85<=result.score<=1
        assert result.caption_bbox==(506,674,78,14) and result.click_point==(545,681)
    assert detector.provenance()["binary_confidence"]=="predicate pass only, not probability"


@pytest.mark.parametrize("change",["reversed","shift","uniform","empty"])
def test_synthetic_shape_negatives_are_distinct_from_actual_classes(change):
    detector=CancelCaptionDetector(BASE/"cancel-caption.json");proto=detector.prototype
    candidate={"reversed":proto[:,::-1].copy(),"shift":np.roll(proto,4,axis=1),
        "uniform":np.ones_like(proto),"empty":np.zeros_like(proto)}[change]
    assert tolerant_shape_score(proto,candidate)<.85


def test_other_action_label_and_existing_normal_are_actual_negative_crops():
    detector=CancelCaptionDetector(BASE/"cancel-caption.json")
    for path in sorted((TRAIN/"end-response-before").glob("frame-*.png")):
        # 欠測は独立testで検出し、別labelとして数えません。
        if path.name=="frame-0009.png":continue
        pixels=read_image(path)
        assert tolerant_shape_score(detector.prototype,yellow_shape(pixels[674:688,714:792]))<.85
    for stage in ("menu","placement","post-unselected","post-inspected"):
        for path in (ROOT/"artifacts/baseline-tester/ASH_NORMAL_INSPECT_TRAIN_v1_20261006"/stage).glob("frame-*.png"):
            assert not detector.detect(read_image(path)).passed


def test_unknown_prompts_stay_blocked_despite_common_positive_caption():
    p=build_pipeline(BASE/"calibration.json",ROOT/"data/decks/thunder-dragon-review/cards.sqlite3",BASE/"solo-route.json",BASE/"ui-rules.json")
    try:
        rows,missing=available_training();negative=0
        for cls,path in rows:
            state=p.perception.process(Frame(read_image(path),0,0,capture_source="saved_image"))
            if cls in {"summon-response-before","summon-response-after","end-response-before","end-response-after"}:continue
            assert state.facts["response.cancel_enabled.opponent_turn_end"].value=="true"
            assert not p.planner.filter_actions(state,state.visible_actions);negative+=1
        assert negative==32 and len(missing)==1
        for path in KNOWN.glob("frame-*.png"):
            state=p.perception.process(Frame(read_image(path),0,0,capture_source="saved_image"))
            actions=p.planner.filter_actions(state,state.visible_actions)
            assert len(actions)==1 and actions[0].source_region=="action.cancel_opponent_turn_end"
            assert p.ui_policy.decide(state,tuple(actions)).action==actions[0]
            assert state.facts["response.cancel_enabled.opponent_turn_end"].source.startswith("caption_shape:")
    finally:close_pipeline(p)


def test_asset_mutation_and_wrong_native_shape_fail_closed(tmp_path):
    shutil.copytree(BASE,tmp_path/"profile")
    detector=CancelCaptionDetector(tmp_path/"profile/cancel-caption.json")
    with pytest.raises(ValueError):detector.detect(np.zeros((720,1279,3),np.uint8))
    path=tmp_path/"profile/cancel-caption.json";path.write_text(path.read_text(encoding="utf-8")+" ",encoding="utf-8")
    with pytest.raises(ValueError):detector.detect(np.zeros((720,1280,3),np.uint8))


@pytest.mark.parametrize("change",["none","wrong_source","low_score","wrong_hash","wrong_bbox","wrong_point","wrong_cal_box"])
def test_goal_checks_fixed_glyph_source_score_bbox_and_point(tmp_path,change):
    from test_response_decline import response_case
    from master_duel_advisor.cancel_caption import PARAMETERS
    tel,rule,state=response_case(tmp_path);step=tel.current_step;before=step["response_before"]
    tel.metadata["recognition_components"]["cancel_caption"]={"config_sha256":"glyph-fixture","parameters":PARAMETERS}
    diagnostic={"score":.9,"config_sha256":"glyph-fixture","caption_bbox":PARAMETERS["caption_bbox"],
                "click_bbox":PARAMETERS["click_bbox"],"click_point":PARAMETERS["click_point"]}
    before["facts"][rule.logical_response_decline.cancel_fact]["source"]="caption_shape:glyph-fixture"
    step["screen_point"]=[645,881]
    tel.metadata["calibration"]["regions"][rule.source_region]["rect"]={"x":456/1280,"y":661/720,"width":178/1280,"height":40/720}
    if change=="wrong_source":before["facts"][rule.logical_response_decline.cancel_fact]["source"]="template:old"
    elif change=="low_score":diagnostic["score"]=.849
    elif change=="wrong_hash":diagnostic["config_sha256"]="wrong"
    elif change=="wrong_bbox":diagnostic["caption_bbox"]=[505,674,78,14]
    elif change=="wrong_point":step["screen_point"]=[646,881]
    elif change=="wrong_cal_box":tel.metadata["calibration"]["regions"][rule.source_region]["rect"]["width"]+=.001
    before["facts"]["response.caption_diagnostic"]=Observation(value=json.dumps(diagnostic),confidence=0,
        observed_at=1,source="diagnostic:not_a_legal_fact").model_dump(mode="json")
    assert tel.goal_confirmed(rule,state)==(change=="none")
