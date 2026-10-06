"""新MSSで意味別Cancel開始を確認。run/clickは呼ばず候補点はreview専用です。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from evaluate_solo_response import check_fixed, build_pipeline_for
from master_duel_advisor.agent_loop import LoopLimits, make_live_loop
from master_duel_advisor.cli import close_pipeline, desktop_rect
from master_duel_advisor.image_io import write_image
from master_duel_advisor.models import Action, GameState


def starting_point(loop,p,action,state,frame,logical_action):
    """宣言された開始childだけの座標レビュー。入力は送信しません。"""
    rule=p.planner.rule_for(action) if action else None
    if (not rule or rule.logical_action!=logical_action or not rule.logical_start
            or (rule.logical_response_decline is None and rule.logical_hand_search_confirmation is None)):
        return None
    point=loop._coordinates(action,frame.pixels.shape,frame=frame,state=state)
    loop.clicker.control.validate_point(*point)
    return point


def preflight(rect,title,output,base,fixed_path,logical_action):
    if output.exists():raise ValueError("新規保存先が必要です")
    fixed=check_fixed(fixed_path);p=build_pipeline_for(base);loop=None
    try:
        loop=make_live_loop(p,rect,output,30,LoopLimits(max_actions=1,max_retries=0,max_seconds=10,settle_seconds=0),title)
        frame=loop.capture.read()
        if frame is None:raise ValueError("新MSS取得失敗または入力活動変化")
        result=p.process(frame);state=GameState.model_validate(result["state"])
        raw=result["recommendation"].get("action");action=Action.model_validate(raw) if raw else None
        point=starting_point(loop,p,action,state,frame,logical_action)
        epoch=loop.clicker.input_epoch()
        passed=bool(point is not None and epoch==frame.input_epoch
            and loop.telemetry.metadata["source_sha256"]==fixed["source_sha256"]
            and loop.telemetry.metadata["recognition_components_sha256"]==fixed["recognition_components_sha256"])
        output.mkdir(parents=True,exist_ok=True);image=output/"frame.png"
        if not write_image(image,frame.pixels):raise OSError("preflight画像保存失敗")
        report={"schema":"solo-response-live-preflight-v1","passed":passed,"input_count":0,"e2e_count":0,
            "logical_action":logical_action,"capture_source":frame.capture_source,"capture_rect":frame.capture_rect,
            "captured_at_monotonic":frame.captured_at,"sequence":frame.sequence,
            "capture_start_perf":frame.capture_start,"capture_end_perf":frame.capture_end,
            "review_saved_at_utc":datetime.now(timezone.utc).isoformat(),
            "input_epoch_before":frame.input_epoch,"input_epoch_after":epoch,"input_epoch_clock":"opaque_session_token",
            "image":str(image),"image_sha256":hashlib.sha256(image.read_bytes()).hexdigest(),
            "screen_point_review_only":point,"state":state.model_dump(mode="json"),"recommendation":result["recommendation"],
            "source_sha256":loop.telemetry.metadata["source_sha256"],
            "recognition_components_sha256":loop.telemetry.metadata["recognition_components_sha256"],
            "notice":"pilotは別の新取得と各step guardを使用。保存画像から入力しません"}
        check_fixed(fixed_path)
        (output/"preflight.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        return report
    finally:
        if loop:loop.telemetry.close("preflight_only_no_input");loop.capture.close()
        close_pipeline(p)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--rect",type=desktop_rect,required=True)
    parser.add_argument("--window-title",default="masterduel");parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--profile-base",type=Path,required=True);parser.add_argument("--fixed",type=Path,required=True)
    parser.add_argument("--logical-action",default="decline_opponent_turn_end")
    args=parser.parse_args();r=preflight(args.rect,args.window_title,args.output,args.profile_base,args.fixed,args.logical_action)
    print(json.dumps({k:r[k] for k in ("passed","input_count","e2e_count","source_sha256","screen_point_review_only")}))
    raise SystemExit(0 if r["passed"] else 1)
