"""画像だけの詳細名レジストリ評価。入力/E2Eを計測しません。"""
from pathlib import Path
import sys
import json
import hashlib
import time
from dataclasses import asdict
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from master_duel_advisor.capture import Frame
from master_duel_advisor.detail_name_registry import DetailNameRegistry
from master_duel_advisor.image_io import read_image


def evaluate(registry_path: Path, manifest: Path, output: Path, repeats: int):
    registry = DetailNameRegistry(registry_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    rows, times = [], []
    for seq, item in enumerate(data["frames"]):
        path = Path(item["image"])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise ValueError(f"評価画像hash不一致: {path}")
        pixels = read_image(str(path))
        if pixels is None:
            raise ValueError(f"画像を読めません: {path}")
        # 保存画像の取得時刻は復元しません。0はoffline用の未指定値です。
        # perf_counterは処理時間だけに使い、実機の鮮度時計へ流用しません。
        frame = Frame(pixels, 0., seq)
        for _ in range(repeats):
            start = time.perf_counter_ns()
            evidence = registry.recognize(frame)
            times.append((time.perf_counter_ns()-start)/1e6)
        rows.append({**item, "mode": "offline_saved_image", "observed_at_semantics": "unspecified_zero_not_capture_time",
                     "frame_seq_semantics": "manifest_index_not_capture_sequence",
                     "evidence": asdict(evidence), "passed": evidence.cid == item["expected_cid"]})
    report = {"registry_sha256": registry.sha256, "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
              "purpose": data["purpose"], "mode": "offline_saved_image", "usable_for_input": False,
              "images": len(rows), "passed": sum(r["passed"] for r in rows),
              "false_cid": sum(r["evidence"]["cid"] is not None and not r["passed"] for r in rows),
              "recognition_only_ms": {"calls": len(times), "average": float(np.mean(times)),
                                      "p50": float(np.percentile(times, 50)), "p95": float(np.percentile(times, 95)), "max": max(times)},
              "input_count": 0, "e2e_count": 0, "rows": rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "rows"}, ensure_ascii=False))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeatsは1以上")
    evaluate(args.registry, args.manifest, args.output, args.repeats)
