"""確認済み操作ログをstate→actionの学習候補へ変換します。"""
import json
from pathlib import Path


def export_dataset(log: Path, output: Path) -> dict:
    if log.resolve() == output.resolve():
        raise ValueError("入力ログと出力先は別にしてください")
    samples = []
    for line in log.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("status") not in {"changed", "duel_ended"} or not entry.get("state_before") or not entry.get("action"):
            continue
        samples.append({"state": entry["state_before"], "action": entry["action"],
                        "state_after": entry.get("state_after"),
                        "verification": entry["status"], "metrics": entry.get("metrics", {}),
                        "screen_before": entry.get("before"), "screen_after": entry.get("after"),
                        "label_quality": "observed_execution_not_optimality"})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        for sample in samples:
            stream.write(json.dumps(sample, ensure_ascii=False, allow_nan=False) + "\n")
    return {"samples": len(samples), "output": str(output)}
