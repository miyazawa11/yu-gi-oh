"""ゲーム入力なしで、超雷龍ルートに必要な実画面設定を検査する。"""
import argparse
import json
from pathlib import Path

from master_duel_advisor.regions import load_calibration
from master_duel_advisor.route_validation import audit_route
from master_duel_advisor.strategy_rules import load_planner


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--book", type=Path, default=Path("data/decks/thunder-dragon-review/colossus-route.json"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/colossus-route-readiness.json"))
    args = parser.parse_args()
    report = audit_route(load_planner(args.book).book, load_calibration(args.calibration), args.calibration.parent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"UI手順: {report['ui_steps']} / 校正不足: {len(report['missing'])} / 構造検査: {report['structural_ready']}")
    raise SystemExit(0 if report["structural_ready"] else 2)
