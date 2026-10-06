from dataclasses import asdict
from pathlib import Path
import json
import numpy as np
import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.detail_name_registry import DetailNameRegistry, ROI
from master_duel_advisor.image_io import read_image

REGISTRY = Path("artifacts/detail-name-registry-v1/registry.json")


@pytest.mark.parametrize("cid", ["9455", "13581", "12950"])
def test_reference_identifies_detail_only(cid):
    registry = DetailNameRegistry(REGISTRY)
    data = json.loads(REGISTRY.read_text(encoding="utf8"))
    item = next(r for r in data["references"] if r["cid"] == cid)
    image = read_image(item["source_image"])
    result = registry.recognize(Frame(image, 42.5, 7))
    assert result.cid == cid
    assert result.namespace == "konami" and result.scope == "selected_detail_only"
    assert result.frame_seq == 7 and result.observed_at == 42.5
    assert result.score >= .98 and result.margin >= .03
    assert not {"slot", "zone", "action"} & asdict(result).keys()


def test_unknown_does_not_retain_previous_cid():
    registry = DetailNameRegistry(REGISTRY)
    known = read_image("artifacts/baseline-tester/CARD_NAME_OCR_EXPLORATION_20261006/ash-first/frame-0000.png")
    assert registry.recognize(Frame(known, 1., 0)).cid == "12950"
    unknown = registry.recognize(Frame(np.zeros((720, 1280, 3), np.uint8), 2., 1))
    assert unknown.cid is None and unknown.unknown_reason == "below_score_threshold"
    assert unknown.frame_seq == 1 and unknown.observed_at == 2.


@pytest.mark.parametrize("pixels", [np.zeros((720, 1279, 3), np.uint8), np.zeros((720, 1280, 3), np.float32)])
def test_invalid_capture_rejected(pixels):
    result = DetailNameRegistry(REGISTRY).recognize(Frame(pixels, 1., 1))
    assert result.cid is None and result.unknown_reason == "invalid_capture_shape_or_dtype"


def test_ambiguous_reference_rejected():
    registry = DetailNameRegistry(REGISTRY)
    cid, feature, digest = registry.references[0]
    registry.references = [(cid, feature, digest), ("12950", feature.copy(), digest), registry.references[2]]
    image = read_image("artifacts/baseline-tester/MAXXC_MENU_TRAIN_v1_full/frame-0000.png")
    result = registry.recognize(Frame(image, 1., 0))
    assert result.cid is None and result.unknown_reason == "ambiguous_margin"


def test_registry_cannot_lower_threshold(tmp_path):
    data = json.loads(REGISTRY.read_text(encoding="utf8"))
    data["minimum_score"] = .90
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(data), encoding="utf8")
    with pytest.raises(ValueError, match="固定条件"):
        DetailNameRegistry(path)


def test_reference_hash_checked(tmp_path):
    data = json.loads(REGISTRY.read_text(encoding="utf8"))
    for item in data["references"]:
        (tmp_path / item["image"]).write_bytes((REGISTRY.parent / item["image"]).read_bytes())
    (tmp_path / data["references"][0]["image"]).write_bytes(b"invalid")
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(data), encoding="utf8")
    with pytest.raises(ValueError, match="ハッシュ"):
        DetailNameRegistry(path)


def test_exploration_manifest_integration():
    registry = DetailNameRegistry(REGISTRY)
    manifest = json.loads(Path("evaluation/detail-name-exploration-manifest-v1.json").read_text(encoding="utf8"))
    assert len(manifest["frames"]) == 75
    for seq, item in enumerate(manifest["frames"]):
        result = registry.recognize(Frame(read_image(item["image"]), 1., seq))
        assert result.cid == item["expected_cid"]


def test_evaluator_marks_saved_images_offline(tmp_path):
    import importlib.util
    path = Path("scripts/evaluate_detail_name_registry.py")
    spec = importlib.util.spec_from_file_location("detail_evaluator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = json.loads(Path("evaluation/detail-name-exploration-manifest-v1.json").read_text(encoding="utf8"))
    source["frames"] = source["frames"][:1]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(source), encoding="utf8")
    output = tmp_path / "report.json"
    module.evaluate(REGISTRY, manifest, output, 1)
    report = json.loads(output.read_text(encoding="utf8"))
    assert report["mode"] == "offline_saved_image" and report["usable_for_input"] is False
    assert report["rows"][0]["evidence"]["observed_at"] == 0.
    assert report["rows"][0]["frame_seq_semantics"] == "manifest_index_not_capture_sequence"
