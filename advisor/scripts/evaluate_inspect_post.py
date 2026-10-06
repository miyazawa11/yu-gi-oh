"""固定後の同scene新MSS postをoffline0で認識評価。履歴無しで入力許可しません。"""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import build_pipeline,close_pipeline
from master_duel_advisor.image_io import read_image

ROOT=Path(__file__).resolve().parents[1]


def evaluate(manifest_path,fixed_path,base):
    fixed=json.loads(fixed_path.read_text(encoding='utf-8'))
    for name,sha in fixed['recognition_components']['files'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=sha:
            raise ValueError('固定source/認識asset hash不一致: '+name)
    frozen=datetime.fromisoformat(fixed['frozen_at_utc'])
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('capture_source')!='mss':
        raise ValueError('元manifestの実MSS取得由来が必要です。offlineをliveへ昇格しません')
    if len(manifest['frames'])!=10 or not all(r['eligible'] for r in manifest['frames']):
        raise ValueError('固定後の適合MSS10枚が必要です')
    pipeline=build_pipeline(base/'calibration.json',ROOT/'data/decks/thunder-dragon-review/cards.sqlite3',base/'normal-route.json')
    rows=[]
    try:
        for index,row in enumerate(manifest['frames']):
            if (not isinstance(row.get('captured_at_monotonic'),(int,float))
                    or not math.isfinite(row['captured_at_monotonic']) or row['captured_at_monotonic']<=0
                    or type(row.get('capture_sequence')) is not int or row['capture_sequence']<0):
                raise ValueError('元取得monotonic/実sequenceが必要です')
            if datetime.fromisoformat(row['capture_start_utc'])<=frozen:
                raise ValueError('固定前の画像は時間的評価に含められません')
            path=(manifest_path.parent/row['file']).resolve()
            if not path.is_relative_to(manifest_path.parent.resolve()):
                raise ValueError('新MSS取得folder以外の画像は評価できません')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
                raise ValueError('元capture画像hash不一致')
            state=pipeline.perception.process(Frame(read_image(path),0,index,capture_source='saved_image'))
            facts=state.facts
            passed=(state.phase.value=='MAIN1' and state.turn_player.value=='self'
                and state.prompt.value=='none' and state.animation.value is False and state.terminal.value is False
                and facts['zone.self.monster_2.occupancy'].value=='occupied'
                and facts['inspect_context.detail_blank'].value=='true'
                and facts['detail.card_id'].value is None
                and any(a.type.value=='SELECT_CARD' and a.source_region=='action.inspect_zone' for a in state.visible_actions))
            allowed=pipeline.planner.filter_actions(state,state.visible_actions)
            rows.append({'index':index,'passed':passed,'original_capture':row,'recognition_observed_at':0,
                'planner_allowed_count':len(allowed),'planner_blocked':pipeline.planner.blocked,
                'state':state.model_dump(mode='json')})
        return {'schema':'ash-post-temporal-recognition-v3','passed':all(r['passed'] for r in rows),
            'cases':len(rows),'input_count':0,'e2e_count':0,'frozen_at_utc':fixed['frozen_at_utc'],
            'source_sha256':fixed['source_sha256'],'manifest':str(manifest_path),
            'original_manifest_metadata':{k:v for k,v in manifest.items() if k!='frames'},
            'evaluation_capture_context':'offline_saved_image_observed_at_zero',
            'scope':'同scene固定後時間的再取得。別場面汎化/目的達成/履歴検証ではない',
            'training_used':False,'rows':rows}
    finally:
        close_pipeline(pipeline)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--fixed',type=Path,default=ROOT/'evaluation/normal-inspect-fixed-v3.json')
    parser.add_argument('--profile-base',type=Path,default=ROOT/'artifacts/ash-normal-inspect-calibration-v3')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); report=evaluate(args.manifest,args.fixed,args.profile_base)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k in ['passed','cases','input_count','e2e_count']},ensure_ascii=False))
    raise SystemExit(0 if report['passed'] else 1)
