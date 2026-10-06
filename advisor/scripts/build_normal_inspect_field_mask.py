"""比較済み単一maskをAsh限定calへ接続。新画像訓練/閾値変更は行いません。"""
import json
import shutil
from pathlib import Path

from master_duel_advisor.cli import build_pipeline,close_pipeline
from master_duel_advisor.regions import Calibration

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'artifacts/ash-normal-inspect-calibration-v2'
OUT=ROOT/'artifacts/ash-normal-inspect-calibration-v3'


if __name__=='__main__':
    for path in OLD.rglob('*'):
        if path.is_file():
            target=OUT/path.relative_to(OLD);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,target)
    raw=json.loads((OUT/'calibration.json').read_text(encoding='utf-8'))
    raw['name']='Ash-left-menu-field-border-inspect-MSS-v3'
    for name in ['fact.zone.self.monster_2.occupancy','action.inspect_zone']:
        raw['regions'][name]['stable_rgb_excluded_rows']=list(range(6,25))
    layout=Calibration.model_validate(raw)
    (OUT/'calibration.json').write_text(layout.model_dump_json(indent=2)+'\n',encoding='utf-8')
    pipeline=build_pipeline(OUT/'calibration.json',ROOT/'data/decks/thunder-dragon-review/cards.sqlite3',OUT/'normal-route.json')
    report={'schema':'ash-field-mask-v3','condition':'stable_rgb descriptor rows6..24 excluded',
        'scope':'Ash中央field表示限定、CID生成無し','source_training':'v2参照維持・新規画像訓練無し',
        'method_selection_diagnostics':['normal-inspect-central-mask-diagnostic-v2.json','normal-inspect-central-mask-contrasts-v2.json'],
        'method_selection_not_holdout':True,'input_count':0,'e2e_count':0,
        'statistics':{name:pipeline.perception.stable_statistics[name] for name in ['fact.zone.self.monster_2.occupancy','action.inspect_zone']}}
    (OUT/'field-mask-provenance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    close_pipeline(pipeline)
