"""固定後の新MSS応答10枚をoffline0で評価。画像をlive入力証拠へ昇格しません。"""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import build_pipeline, close_pipeline
from master_duel_advisor.image_io import read_image
from master_duel_advisor.telemetry import value_hash
from master_duel_advisor.cancel_caption import diagnostic_output_path

ROOT=Path(__file__).resolve().parents[1]


def check_fixed(path):
    fixed=json.loads(Path(path).read_text(encoding="utf-8"))
    for file,sha in {**fixed["recognition_components"]["files"],**fixed["files"]}.items():
        if hashlib.sha256(Path(file).read_bytes()).hexdigest()!=sha:
            raise ValueError("固定source/asset/helper hash不一致: "+file)
    return fixed


def build_pipeline_for(base):
    return build_pipeline(base/"calibration.json",ROOT/"data/decks/thunder-dragon-review/cards.sqlite3",
                          base/"solo-route.json",base/"ui-rules.json")


def evaluate(manifest_path,fixed_path,base,logical_action):
    fixed=check_fixed(fixed_path)
    frozen=datetime.fromisoformat(fixed["frozen_at_utc"])
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("capture_source")!="mss" or len(manifest["frames"])!=10
            or not all(r["eligible"] for r in manifest["frames"])):
        raise ValueError("固定後の適合MSS10枚が必要です")
    p=build_pipeline_for(base);rows=[]
    try:
        if value_hash(p.perception.recognition_components)!=fixed["recognition_components_sha256"]:
            raise ValueError("校正baseの固定component不一致")
        rule=next(r for r in p.planner.book.rules if r.logical_action==logical_action and r.logical_start)
        if rule.logical_response_decline is None and rule.logical_hand_search_confirmation is None:
            raise ValueError("意味別辞退またはhand-searchの開始目的を指定してください")
        for item in manifest["frames"]:
            if (type(item.get("captured_at_monotonic")) not in (int,float)
                    or not math.isfinite(item["captured_at_monotonic"]) or item["captured_at_monotonic"]<=0
                    or type(item.get("capture_sequence")) is not int or item["capture_sequence"]<0
                    or datetime.fromisoformat(item["capture_start_utc"])<=frozen):
                raise ValueError("原時計/sequence/固定後UTCが必要です")
            path=(manifest_path.parent/item["file"]).resolve()
            if not path.is_relative_to(manifest_path.parent.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=item["sha256"]:
                raise ValueError("保存画像path/hash不一致")
            state=p.perception.process(Frame(read_image(path),0,item["capture_sequence"],capture_source="saved_image"))
            actions=p.planner.filter_actions(state,state.visible_actions)
            choice=p.ui_policy.decide(state,tuple(actions))
            passed=bool(choice and choice.action and rule.matches(choice.action) and not rule.missing(state,.98))
            rows.append({"passed":passed,"original_capture":item,"recognition_observed_at":0,
                "state":state.model_dump(mode="json"),"strict_candidates":[a.model_dump(mode="json") for a in actions],
                "ui_policy":choice.model_dump(mode="json") if choice else None})
        check_fixed(fixed_path)
        return {"schema":"solo-response-temporal-v1","passed":all(r["passed"] for r in rows),"cases":len(rows),
            "input_count":0,"e2e_count":0,"logical_action":logical_action,"training_used":False,
            "source_sha256":fixed["source_sha256"],"manifest":str(manifest_path),
            "original_manifest_metadata":{k:v for k,v in manifest.items() if k!="frames"},
            "evaluation_capture_context":"offline_saved_image_observed_at_zero",
            "scope":"同scene固定後時間的再取得。別scene汎化/実入力/E2Eの評価ではありません", "rows":rows}
    finally:close_pipeline(p)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--fixed",type=Path,required=True);parser.add_argument("--profile-base",type=Path,required=True)
    parser.add_argument("--logical-action",default="decline_opponent_turn_end");parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text(encoding="utf-8"));fixed=json.loads(args.fixed.read_text(encoding="utf-8"))
    input_paths={args.manifest.resolve(),args.fixed.resolve(),
        *(args.manifest.parent/item["file"] for item in manifest["frames"]),*args.profile_base.rglob("*"),
        *(Path(name) for name in {**fixed["files"],**fixed["recognition_components"]["files"]})}
    output=diagnostic_output_path(args.output,input_paths,ROOT/"evaluation")
    report=evaluate(args.manifest,args.fixed,args.profile_base,args.logical_action)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("passed","cases","input_count","e2e_count")}))
    raise SystemExit(0 if report["passed"] else 1)
