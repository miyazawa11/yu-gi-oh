"""固定局所探索の保存画像評価。訓練・診断・独立holdoutを混ぜません。"""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from master_duel_advisor.action_evidence import ActionEvidenceDetector, CaptureContext, PROFILES
from master_duel_advisor.capture import Frame
from master_duel_advisor.image_io import read_image
from master_duel_advisor.perception import TemplateMatcher
from master_duel_advisor.regions import load_calibration


def summary(values):
    if not values:
        return {"calls": 0, "average": None, "p50": None, "p90": None, "p95": None, "max": None}
    return {"calls": len(values), "average": float(np.mean(values)), "p50": float(np.percentile(values, 50)),
            "p90": float(np.percentile(values, 90)), "p95": float(np.percentile(values, 95)), "max": max(values)}


def utc_time(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError("独立資料の時刻はtimezone付きISO8601が必要です") from None
    if parsed.tzinfo is None:
        raise ValueError("独立資料の時刻にはtimezoneが必要です")
    return parsed.astimezone(timezone.utc)


def evaluate(config_path: Path, manifest: Path, output: Path, repeats: int = 1):
    if repeats < 1:
        raise ValueError("反復は1回以上です")
    detector = ActionEvidenceDetector(config_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if (data.get("schema") != "action-evidence-evaluation-v1" or not data.get("frames")
            or data.get("detector_sha256") != detector.sha256
            or data.get("dataset_kind") not in {"training_and_diagnostic", "independent_holdout"}):
        raise ValueError("評価manifestの固定条件が一致しません")
    if data["dataset_kind"] == "independent_holdout":
        if (not data.get("frozen_at_utc") or not data.get("collector") or not data.get("collection_started_utc")
                or utc_time(data["collection_started_utc"]) <= utc_time(data["frozen_at_utc"])):
            raise ValueError("独立holdoutには固定後の取得時刻と収集担当が必要です")
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    fixed_matchers = {}
    for name, item in raw["profiles"].items():
        path = (config_path.parent / item["calibration"]).resolve()
        layout = load_calibration(path)
        region = layout.regions["action.normal_summon"]
        fixed_matchers[name] = (region, TemplateMatcher(region, path.parent))
    context = CaptureContext(mode="offline_saved_image", capture_source="saved_MSS_client_image",
                             captured_at_clock="unspecified_zero_not_capture_time",
                             frame_seq_semantics="manifest_index_not_capture_sequence")
    rows, timings, baseline_times, crop_times = [], [], [], []
    seen = set()
    unique_images = set()
    detector.assert_assets_unchanged(full_hash=True)
    for seq, item in enumerate(data["frames"]):
        path = Path(item["image"])
        if not path.is_absolute():
            path = manifest.parent / path
        key = (str(path.resolve()), item["profile_id"], item.get("evaluation_scope", "local_search"))
        if key in seen:
            raise ValueError("同一評価対象を重複して精度標本に加算しません")
        seen.add(key)
        unique_images.add(str(path.resolve()))
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("評価画像のhashが一致しません: " + str(path))
        pixels = read_image(path)
        if pixels is None:
            raise ValueError("評価画像を読み込めません")
        if not isinstance(item.get("expected_detected"), bool) or not item.get("reviewed_label"):
            raise ValueError("評価対象には目視ラベルと期待値が必要です")
        if data["dataset_kind"] == "independent_holdout" and item.get("sample_role") != "independent_holdout":
            raise ValueError("独立holdoutへ訓練または診断資料を混ぜません")
        if data["dataset_kind"] == "independent_holdout" and (not item.get("capture_start_utc")
                or utc_time(item["capture_start_utc"]) <= utc_time(data["frozen_at_utc"])
                or not item.get("original_capture_manifest")):
            raise ValueError("独立frameには固定後の取得時刻と原capture manifestが必要です")
        profile = item["profile_id"]
        scope = item.get("evaluation_scope", "local_search")
        if scope == "crop_similarity_diagnostic":
            box = tuple(item["diagnostic_bbox"])
            for _ in range(repeats):
                started = time.perf_counter_ns()
                score = detector.score_crop(pixels, profile, box)
                crop_times.append((time.perf_counter_ns() - started) / 1e6)
            detected = score >= .98
            evidence = {"crop_score": score, "bbox": box, "scope": scope, "usable_for_input": False}
            bbox_pass = True
            position_validation = False
        elif scope == "local_search":
            frame = Frame(pixels, 0., seq)
            for _ in range(repeats):
                # 取得・画像復号を除外。固定ROI側にはcropと旧matchを含めます。
                region, matcher = fixed_matchers[profile]
                started = time.perf_counter_ns()
                matcher.match(region.rect.crop(pixels))
                baseline_times.append((time.perf_counter_ns() - started) / 1e6)
                started = time.perf_counter_ns()
                result = detector.recognize(frame, context, profile)
                timings.append((time.perf_counter_ns() - started) / 1e6)
            evidence = result.model_dump(mode="json")
            detected = result.candidate_type is not None
            expected_box = item.get("expected_evidence_bbox")
            tolerance = item.get("bbox_tolerance_pixels", 0)
            if (isinstance(tolerance, bool) or not isinstance(tolerance, int) or not 0 <= tolerance <= 3
                    or (expected_box is not None and (not isinstance(expected_box, list) or len(expected_box) != 4))
                    or (item["expected_detected"] and expected_box is None and item.get("position_groundtruth") != "unverified")):
                raise ValueError("陽性は期待crop/0〜3px許容値、またはposition_groundtruth=unverifiedが必要です")
            position_validation = item["expected_detected"] and expected_box is not None
            bbox_pass = (None if item["expected_detected"] and expected_box is None else
                         expected_box is None or (result.evidence_bbox is not None
                        and all(abs(a-b) <= tolerance for a, b in zip(result.evidence_bbox, expected_box))))
        else:
            raise ValueError("未対応の評価範囲です")
        rows.append({**item, "observed_at_semantics": "unspecified_zero_not_capture_time",
                     "frame_seq_semantics": "manifest_index_not_capture_sequence", "evidence": evidence,
                     "detected": detected, "bbox_passed": bbox_pass, "position_validation": position_validation,
                     "detection_passed": detected == item["expected_detected"],
                     "passed": detected == item["expected_detected"] and bbox_pass is True})
    detector.assert_assets_unchanged(full_hash=True)
    groups = {}
    for row in rows:
        group = groups.setdefault(row["sample_role"], {"cases": 0, "passed": 0, "detection_passed": 0,
                                                      "position_unverified": 0, "false_positive": 0, "false_negative": 0})
        group["cases"] += 1
        group["passed"] += int(row["passed"])
        group["detection_passed"] += int(row["detection_passed"])
        group["position_unverified"] += int(row["bbox_passed"] is None)
        group["false_positive"] += int(row["detected"] and not row["expected_detected"])
        group["false_negative"] += int(not row["detected"] and row["expected_detected"])
    report = {"schema": "action-evidence-evaluation-report-v1", "purpose": data["purpose"],
              "dataset_kind": data["dataset_kind"], "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
              "mode": "offline_saved_image", "usable_for_input": False, "provenance": detector.provenance(),
              "cases": len(rows), "unique_images": len(unique_images), "passed_cases": sum(r["passed"] for r in rows),
              "passed": all(r["passed"] for r in rows), "groups": groups,
              "detection_passed": all(r["detection_passed"] for r in rows),
              "joint_position_passed": all(r["passed"] for r in rows),
              "search_only_ms": summary(timings), "fixed_roi_only_ms": summary(baseline_times),
              "crop_diagnostic_only_ms": summary(crop_times), "input_count": 0, "e2e_count": 0,
              "rows": rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    report = evaluate(args.config, args.manifest, args.output, args.repeats)
    print(json.dumps({k: v for k, v in report.items() if k not in {"rows", "provenance"}}, ensure_ascii=False))
    # 採用有無の評価だけが合格しても、位置・入力の合格とは扱いません。
    return 0 if report["detection_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
