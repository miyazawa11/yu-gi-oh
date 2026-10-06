"""限定Ash開始状態を新MSSで確認します。run/clickは呼ばず、入力数は0です。"""
import argparse
import hashlib
import json
from pathlib import Path

from master_duel_advisor.agent_loop import LoopLimits, make_live_loop
from master_duel_advisor.cli import build_pipeline, close_pipeline, desktop_rect
from master_duel_advisor.image_io import write_image
from master_duel_advisor.models import Action, GameState

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'artifacts/ash-normal-inspect-calibration-v1'


def preflight(rect, title, output, base=BASE):
    if output.exists():
        raise ValueError('新規のpreflight保存先を指定してください')
    pipeline=build_pipeline(base/'calibration.json',ROOT/'data/decks/thunder-dragon-review/cards.sqlite3',base/'normal-route.json')
    loop=None
    try:
        loop=make_live_loop(pipeline,rect,output,30,LoopLimits(max_actions=3,max_retries=0,max_seconds=15),title)
        frame=loop.capture.read()
        if frame is None:
            raise ValueError('新MSS取得中に入力活動が変化または取得失敗しました')
        result=pipeline.process(frame)
        state=GameState.model_validate(result['state'])
        raw=result['recommendation'].get('action')
        action=Action.model_validate(raw) if raw else None
        point=None
        if action is not None and action.type.value=='NORMAL_SUMMON':
            point=loop._coordinates(action,frame.pixels.shape,frame=frame,state=state)
            loop.clicker.control.validate_point(*point)
        epoch=loop.clicker.input_epoch()
        passed=bool(action is not None and action.type.value=='NORMAL_SUMMON' and point is not None
                    and epoch==frame.input_epoch and pipeline.planner.rule_for(action).logical_start)
        output.mkdir(parents=True,exist_ok=True)
        image_path=output/'frame.png'
        if not write_image(image_path,frame.pixels):
            raise OSError('preflight画像保存失敗')
        report={'schema':'normal-inspect-live-preflight-v1','passed':passed,'input_count':0,'e2e_count':0,
            'capture_source':frame.capture_source,'capture_rect':frame.capture_rect,'sequence':frame.sequence,
            'captured_at_monotonic':frame.captured_at,'capture_start_perf':frame.capture_start,'capture_end_perf':frame.capture_end,
            'input_epoch_before':frame.input_epoch,'input_epoch_after':epoch,'input_epoch_clock':'opaque_session_token',
            'image':str(image_path),'image_sha256':hashlib.sha256(image_path.read_bytes()).hexdigest(),
            'screen_point_review_only':point,'state':state.model_dump(mode='json'),'recommendation':result['recommendation'],
            'source_sha256':loop.telemetry.metadata['source_sha256'],
            'recognition_components_sha256':loop.telemetry.metadata['recognition_components_sha256'],
            'notice':'保存画像・候補点は入力許可ではありません。pilotは別の新MSSと各step guardを使用します'}
        (output/'preflight.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return report
    finally:
        if loop:
            loop.telemetry.close('preflight_only_no_input')
            loop.capture.close()
        close_pipeline(pipeline)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rect',type=desktop_rect,required=True)
    parser.add_argument('--window-title',default='masterduel')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--profile-base',type=Path,default=BASE)
    args=parser.parse_args()
    report=preflight(args.rect,args.window_title,args.output,args.profile_base)
    print(json.dumps({k:v for k,v in report.items() if k in ['passed','input_count','e2e_count','source_sha256','screen_point_review_only']},ensure_ascii=False))
    raise SystemExit(0 if report['passed'] else 1)
