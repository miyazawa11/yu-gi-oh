"""ローカルLLMの合成候補での接続・速度検証。ゲームへの入力なし。"""
import argparse
import json
import time
from pathlib import Path

from master_duel_advisor.local_strategy import LocalStrategy
from master_duel_advisor.llm_fallback import StrategyChoice

parser = argparse.ArgumentParser()
parser.add_argument("--model", required=True)
parser.add_argument("--runs", type=int, default=5)
parser.add_argument("--timeout", type=float, default=120)
parser.add_argument("--output", type=Path, default=Path("artifacts/local-inference-validation.json"))
args = parser.parse_args()
if not 1 <= args.runs <= 20:
    parser.error("runsは1〜20で指定してください")
provider = LocalStrategy(args.model, timeout=args.timeout)
payload = {"test_only": True, "phase": "DUEL_RESULT", "visible_actions": [
    {"type": "CONFIRM", "source_region": "action.result_ok", "card_id": None,
     "target": None, "confidence": 1, "description": "対戦結果を閉じる"}]}
records = []
for index in range(args.runs):
    started = time.perf_counter()
    try:
        choice = provider(payload, StrategyChoice.model_json_schema())
        expected = payload["visible_actions"][0]
        matched = all(choice[key] == expected[key] for key in ("type", "source_region", "card_id", "target"))
        result = {"candidate_matched": matched, "accepted_confidence": choice["confidence"] >= .98}
    except Exception as exc:
        result = {"error": str(exc)}
    result.update(run=index, elapsed_ms=round((time.perf_counter()-started)*1000, 2))
    records.append(result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps({"model": args.model, "synthetic": True, "game_inputs": 0,
    "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
