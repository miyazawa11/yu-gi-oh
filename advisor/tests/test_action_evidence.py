import importlib.util
import json
from pathlib import Path
import shutil

import numpy as np
import pytest
from pydantic import ValidationError

from master_duel_advisor.action_evidence import ActionEvidenceDetector, CaptureContext, PROFILES
from master_duel_advisor.capture import Frame
from master_duel_advisor.image_io import read_image

CONFIG = Path("evaluation/action-evidence-detector-v1.json")
MANIFEST = Path("evaluation/action-evidence-exploration-manifest-v1.json")
MENU = Path("artifacts/baseline-tester/MAXXC_MENU_TRAIN_v1_full/frame-0000.png")
OFFLINE = CaptureContext(mode="offline_saved_image", capture_source="saved_MSS",
                         captured_at_clock="unspecified_zero_not_capture_time",
                         frame_seq_semantics="manifest_index_not_capture_sequence")
LIVE = CaptureContext(mode="live_capture", capture_source="MSS",
                      captured_at_clock="monotonic", frame_seq_semantics="capture_sequence",
                      client_rect=(-1918, 817, -638, 1537))


@pytest.fixture(scope="module")
def detector():
    return ActionEvidenceDetector(CONFIG)


def copied_config(tmp_path):
    data = json.loads(CONFIG.read_text(encoding="utf8"))
    for name, item in data["profiles"].items():
        source = (CONFIG.parent / item["calibration"]).resolve()
        folder = tmp_path / name
        folder.mkdir()
        shutil.copyfile(source, folder / "calibration.json")
        for asset in item["template_assets"]:
            target = folder / asset
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source.parent / asset, target)
        item["calibration"] = name + "/calibration.json"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf8")
    return path, data


def evaluator():
    spec = importlib.util.spec_from_file_location("action_evidence_evaluator", Path("scripts/evaluate_action_evidence.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_metadata_retained_but_no_input_and_no_card_zone(detector):
    result = detector.recognize(Frame(read_image(MENU), 42.25, 11), LIVE, "maxxc-menu-v1")
    assert result.candidate_type == "NORMAL_SUMMON"
    assert result.evidence_bbox == PROFILES["maxxc-menu-v1"]
    assert result.observed_at == 42.25 and result.frame_seq == 11
    assert result.capture_context.client_rect == LIVE.client_rect
    assert result.usable_for_input is False
    assert result.type_runner_up is None and result.type_margin is None
    assert "SPECIAL_SUMMON" in result.unverified_alternatives
    assert not {"card_id", "zone", "click_point", "coordinate"} & result.model_dump().keys()
    with pytest.raises(ValidationError):
        type(result).model_validate({**result.model_dump(), "usable_for_input": True})
    with pytest.raises(ValidationError):
        result.score = .5


@pytest.mark.parametrize("pixels,reason", [
    (np.zeros((720, 1279, 3), np.uint8), "invalid_capture_shape_or_dtype"),
    (np.zeros((720, 1280, 3), np.float32), "invalid_capture_shape_or_dtype"),
    (np.zeros((720, 1280, 3), np.uint8), "below_score_threshold"),
])
def test_shape_dtype_and_blank_fail_closed(detector, pixels, reason):
    result = detector.recognize(Frame(pixels, 0., 0), OFFLINE, "maxxc-menu-v1")
    assert result.candidate_type is None and result.unknown_reason == reason


@pytest.mark.parametrize("timestamp,seq,context,reason", [
    (float("nan"), 0, OFFLINE, "invalid_frame_metadata"),
    (float("inf"), 0, OFFLINE, "invalid_frame_metadata"),
    (-1., 0, OFFLINE, "invalid_frame_metadata"),
    (0., -1, OFFLINE, "invalid_frame_metadata"),
    (0., True, OFFLINE, "invalid_frame_metadata"),
    (1., 0, OFFLINE, "offline_frame_cannot_be_freshened"),
    (0., 0, LIVE, "invalid_live_capture_provenance"),
    (1., 0, LIVE.model_copy(update={"client_rect": None}), "invalid_live_capture_provenance"),
    (1., 0, LIVE.model_copy(update={"client_rect": (0, 0, 1281, 720)}), "client_rect_shape_mismatch"),
    (1., 0, LIVE.model_copy(update={"captured_at_clock": "unspecified_zero_not_capture_time"}), "invalid_live_capture_provenance"),
])
def test_bad_metadata_and_saved_image_freshening_rejected(detector, timestamp, seq, context, reason):
    result = detector.recognize(Frame(read_image(MENU), timestamp, seq), context, "maxxc-menu-v1")
    assert result.candidate_type is None and result.unknown_reason == reason
    json.dumps(result.model_dump(mode="json"), allow_nan=False)


def test_same_icon_is_not_card_identity(detector):
    result = detector.recognize(Frame(read_image(MENU), 0., 0), OFFLINE, "solar-menu-v2")
    assert result.candidate_type == "NORMAL_SUMMON" and result.score >= .98
    assert result.evidence_bbox[:2] == (434, 497)
    assert result.usable_for_input is False


def test_two_separate_button_hypotheses_are_ambiguous(detector):
    pixels = read_image(MENU)
    x, y, w, h = PROFILES["maxxc-menu-v1"]
    crop = pixels[y:y+h, x:x+w].copy()
    synthetic = np.zeros_like(pixels)
    for xx in [x - 40, x + 40]:
        synthetic[y:y+h, xx:xx+w] = crop
    result = detector.recognize(Frame(synthetic, 0., 0), OFFLINE, "maxxc-menu-v1")
    assert result.score >= .98 and result.position_runner_up_score >= .98
    assert result.position_margin < .03
    assert result.candidate_type is None and result.unknown_reason == "ambiguous_position_margin"


def test_local_search_follows_translated_pixels_within_fixed_bounds(detector):
    pixels = read_image(MENU)
    x, y, w, h = PROFILES["maxxc-menu-v1"]
    synthetic = np.zeros_like(pixels)
    synthetic[y+8:y+8+h, x-12:x-12+w] = pixels[y:y+h, x:x+w]
    result = detector.recognize(Frame(synthetic, 0., 0), OFFLINE, "maxxc-menu-v1")
    assert result.candidate_type == "NORMAL_SUMMON" and result.evidence_bbox == (x-12, y+8, w, h)
    assert result.usable_for_input is False  # 合成座標試験は実機入力の検証ではありません。


@pytest.mark.parametrize("bbox", [(-1, 496, 73, 98), (1270, 496, 73, 98), (434, 496, 74, 98), (434., 496, 73, 98)])
def test_crop_diagnostic_never_accepts_bad_bounds_or_shape(detector, bbox):
    with pytest.raises(ValueError):
        detector.score_crop(read_image(MENU), "maxxc-menu-v1", bbox)


def test_config_cannot_lower_threshold(tmp_path):
    data = json.loads(CONFIG.read_text(encoding="utf8"))
    data["minimum_score"] = .90
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf8")
    with pytest.raises(ValueError, match="固定条件"):
        ActionEvidenceDetector(path)


def test_asset_hash_change_rejected_at_load_and_after_freeze(tmp_path):
    path, data = copied_config(tmp_path)
    instance = ActionEvidenceDetector(path)
    item = data["profiles"]["maxxc-menu-v1"]
    asset = path.parent / Path(item["calibration"]).parent / next(iter(item["template_assets"]))
    asset.write_bytes(b"invalid")
    with pytest.raises(ValueError, match="変更"):
        instance.recognize(Frame(read_image(MENU), 0., 0), OFFLINE, "maxxc-menu-v1")
    with pytest.raises(ValueError):
        ActionEvidenceDetector(path)


def test_full_content_hash_rejects_same_size_timestamp_restore(tmp_path):
    import os
    path, data = copied_config(tmp_path)
    instance = ActionEvidenceDetector(path)
    item = data["profiles"]["solar-menu-v2"]
    asset = path.parent / Path(item["calibration"]).parent / next(iter(item["template_assets"]))
    stat = asset.stat()
    raw = asset.read_bytes()
    asset.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    os.utime(asset, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(ValueError, match="変更"):
        instance.assert_assets_unchanged(full_hash=True)


def test_saved_image_evaluator_keeps_training_and_diagnostics_separate(tmp_path):
    data = json.loads(MANIFEST.read_text(encoding="utf8"))
    # manifest移動時は画像の元pathを絶対化。3件は独立精度標本ではありません。
    data["frames"] = [data["frames"][0], data["frames"][40], data["frames"][48]]
    for item in data["frames"]:
        item["image"] = str((MANIFEST.parent / item["image"]).resolve())
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(data), encoding="utf8")
    report = evaluator().evaluate(CONFIG, manifest, tmp_path / "report.json")
    assert report["passed"] and report["usable_for_input"] is False and report["e2e_count"] == 0
    assert report["groups"]["training_positive"]["cases"] == 1
    assert report["groups"]["reviewed_no_button_diagnostic"]["cases"] == 1
    assert report["groups"]["reviewed_set_crop_diagnostic"]["cases"] == 1
    assert report["cases"] == 3 and report["unique_images"] == 2
    assert report["rows"][0]["evidence"]["observed_at"] == 0
    assert report["rows"][0]["frame_seq_semantics"] == "manifest_index_not_capture_sequence"
    assert report["provenance"]["component_source_sha256"]["action_evidence"]


def test_fixed_real_images_integration(detector):
    data = json.loads(MANIFEST.read_text(encoding="utf8"))
    assert len(data["frames"]) == 50
    for seq, item in enumerate(data["frames"]):
        pixels = read_image(MANIFEST.parent / item["image"])
        if item.get("evaluation_scope") == "crop_similarity_diagnostic":
            assert detector.score_crop(pixels, item["profile_id"], tuple(item["diagnostic_bbox"])) < .98
            continue
        result = detector.recognize(Frame(pixels, 0., seq), OFFLINE, item["profile_id"])
        assert (result.candidate_type is not None) is item["expected_detected"]
        if item["expected_detected"]:
            assert result.evidence_bbox == tuple(item["expected_evidence_bbox"])
        assert result.usable_for_input is False


def test_independent_holdout_requires_freeze_and_collection(tmp_path):
    data = json.loads(MANIFEST.read_text(encoding="utf8"))
    data["dataset_kind"] = "independent_holdout"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf8")
    with pytest.raises(ValueError, match="固定後"):
        evaluator().evaluate(CONFIG, path, tmp_path / "output.json")


def test_unverified_bbox_is_not_position_pass(tmp_path):
    data = json.loads(MANIFEST.read_text(encoding="utf8"))
    item = data["frames"][0]
    item["image"] = str((MANIFEST.parent / item["image"]).resolve())
    item["expected_evidence_bbox"] = None
    item["position_groundtruth"] = "unverified"
    data["frames"] = [item]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf8")
    result = evaluator().evaluate(CONFIG, path, tmp_path / "report.json")
    assert result["detection_passed"] and not result["joint_position_passed"] and not result["passed"]
    assert result["rows"][0]["bbox_passed"] is None
    assert result["rows"][0]["position_validation"] is False
    assert result["groups"]["training_positive"]["position_unverified"] == 1
