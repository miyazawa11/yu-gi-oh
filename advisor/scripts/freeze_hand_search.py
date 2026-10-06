"""新hand pilotのsource/assets/helper/上限を取得前に固定。UI操作は行いません。"""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

from evaluate_solo_response import build_pipeline_for,check_fixed
from master_duel_advisor.agent_loop import LoopLimits
from master_duel_advisor.cancel_caption import diagnostic_output_path
from master_duel_advisor.cli import close_pipeline
from master_duel_advisor.telemetry import ActionTelemetry,load_trials,value_hash

ROOT=Path(__file__).resolve().parents[1]
PILOT_LIMITS=LoopLimits(max_actions=3,max_seconds=20.0,max_retries=0,max_same_action=1,
    verify_seconds=8.0,verify_poll_seconds=.05,settle_seconds=0.0)


def freeze(base,output):
    base=base.resolve()
    if not base.is_relative_to(ROOT/"artifacts"):raise ValueError("workspace artifact校正が必要です")
    paths={p.resolve() for folder in [base,ROOT/"src/master_duel_advisor",ROOT/"scripts",ROOT/"tests"]
        for p in folder.rglob("*") if p.is_file() and (folder==base or p.suffix==".py")}
    paths.add(ROOT/"evaluation/solo-cancel-training-input-incident-v1.json")
    db=ROOT/"data/decks/thunder-dragon-review/cards.sqlite3";paths.add(db)
    output=diagnostic_output_path(output,paths,ROOT/"evaluation")
    p=build_pipeline_for(base)
    try:
        limits=PILOT_LIMITS
        tel=ActionTelemetry(output.parent/"unused-no-runtime",mode="synthetic")
        trial=load_trials(base/"hand-search-trials.json",p.planner)
        fixed={"schema":"hand-search-pilot-fixed-v1","frozen_at_utc":datetime.now(timezone.utc).isoformat(),
            "source_sha256":tel.metadata["source_sha256"],"profile_base":str(base),
            "recognition_components":p.perception.recognition_components,
            "recognition_components_sha256":value_hash(p.perception.recognition_components),
            "limits":asdict(limits),"limits_sha256":value_hash(asdict(limits)),
            "trials":trial,"run_purpose":"pilot","fps":30,"backend":"mss",
            "files":{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)},
            "raw_calibration_sha256":hashlib.sha256((base/"calibration.json").read_bytes()).hexdigest(),
            "route_sha256":hashlib.sha256((base/"solo-route.json").read_bytes()).hexdigest(),
            "scope":"雷電龍source hand6/7 slot3のみ。destinationは実incoming handoff。3 childで1目的。",
            "notice":"binary shapeは確率ではない。保存画像から入力しない。公開anchor見逃し/位相依存は安全停止。",
            "unrelated_training_incident":"旧応答訓練82中1元画像欠測は保全。既存派生運用assetを使用、復元/82再現主張なし"}
        output.write_text(json.dumps(fixed,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        check_fixed(output)
        return fixed
    finally:close_pipeline(p)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--profile-base",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();fixed=freeze(args.profile_base,args.output)
    print(json.dumps({k:fixed[k] for k in ["source_sha256","recognition_components_sha256","raw_calibration_sha256","route_sha256"]}))
