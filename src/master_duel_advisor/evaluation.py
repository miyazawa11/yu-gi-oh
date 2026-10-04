from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from .capture import Frame
from .pipeline import Pipeline, save_json
from .tracking import state_observations


def evaluate(dataset: Path, pipeline: Pipeline, output: Path) -> dict:
    data = json.loads(dataset.read_text(encoding="utf-8"))
    samples = data.get("samples", [])
    if not samples:
        raise ValueError("評価には正解ラベル付きのサンプルが1件以上必要です")
    if data.get("kind") not in {"synthetic", "real_game"}:
        raise ValueError("データ種別には synthetic または real_game を指定してください")
    counts: dict[str, dict[str, int]] = {}
    exact_states = 0
    action_exact = 0
    recommendation_exact = 0
    latency = []
    errors = []
    for index, sample in enumerate(samples):
        pixels = cv2.imread(str(dataset.parent/sample["image"]))
        if pixels is None:
            raise ValueError(f"サンプルを読み込めません: {index}")
        expected = sample.get("expected", {})
        if not expected:
            raise ValueError("各サンプルには独立して付けた正解ラベルが必要です")
        result = pipeline.process(Frame(pixels, time.monotonic(), index))
        from .models import GameState
        observations = state_observations(GameState.model_validate(result["state"]))
        correct_state = True
        for field, target in expected.items():
            if field not in observations:
                # Missing configured zones count as unknown, never a dropped label.
                prediction = None
            else:
                prediction = observations[field].model_dump(mode="json")["value"]
            count = counts.setdefault(field, {"total": 0, "correct": 0, "tp": 0, "fp": 0, "fn": 0})
            count["total"] += 1
            correct = prediction == target
            count["correct"] += int(correct)
            if prediction is not None:
                count["tp" if correct and target is not None else "fp"] += 1
            if target is not None and not correct:
                count["fn"] += 1
            correct_state = correct_state and correct
            if not correct:
                errors.append({"sample": index, "field": field, "expected": target, "actual": prediction})
        exact_states += int(correct_state)
        if "actions" not in sample or "recommendation" not in sample:
            raise ValueError("各サンプルには行動候補と推奨の正解ラベルが必要です")
        predicted_actions = sorted(a["type"] for a in result["legal_actions"])
        actual_recommendation = result["recommendation"]["action"]
        actual_recommendation = actual_recommendation["type"] if actual_recommendation else None
        action_ok = predicted_actions == sorted(sample["actions"])
        recommendation_ok = actual_recommendation == sample["recommendation"]
        action_exact += int(action_ok)
        recommendation_exact += int(recommendation_ok)
        if not action_ok or not recommendation_ok:
            errors.append({"sample": index, "field": "actions/decision", "expected_actions": sample["actions"], "actual_actions": predicted_actions, "expected_recommendation": sample["recommendation"], "actual_recommendation": actual_recommendation})
        latency.append(result["metrics"]["total_compute_ms"])
    fields = {field: {**count, "accuracy": count["correct"]/count["total"], "precision": count["tp"]/(count["tp"]+count["fp"]) if count["tp"]+count["fp"] else None, "recall": count["tp"]/(count["tp"]+count["fn"]) if count["tp"]+count["fn"] else None} for field, count in counts.items()}
    required = {"self.lp", "opponent.lp", "phase", "turn_player", "turn"}
    # 難しい項目の省略や未知ラベルだけのデータで合格するのを防ぎます。
    gate = data["kind"] == "real_game" and required <= fields.keys() and all(fields[f]["accuracy"] >= 0.95 and fields[f]["tp"] >= 20 and fields[f]["recall"] is not None and fields[f]["recall"] >= 0.95 for f in required) and action_exact == len(samples)
    report = {"run_at": datetime.now(timezone.utc).isoformat(), "dataset": str(dataset), "dataset_kind": data["kind"], "sample_count": len(samples), "fields": fields, "game_state_exact_accuracy": exact_states/len(samples), "action_exact_accuracy": action_exact/len(samples), "recommendation_exact_accuracy": recommendation_exact/len(samples), "total_compute_ms": {"mean": float(np.mean(latency)), "p95": float(np.percentile(latency, 95))}, "api_calls": 0, "api_cost_usd": 0, "real_perception_gate_passed": gate, "errors": errors, "limitations": ["行動の正解は対応する UI 候補を対象とし、全ルールを網羅していません", "合成データから実ゲームの精度を証明することはできません", "処理時間は実画面の変化から結果表示までの遅延ではありません"]}
    save_json(output, report)
    return report
