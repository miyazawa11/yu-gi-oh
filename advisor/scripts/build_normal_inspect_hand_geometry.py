"""v4を保ち、既知単一条件の手札形状証拠をv5へ接続。新画像訓練は追加しません。"""
import hashlib
import json
from pathlib import Path
import shutil

from master_duel_advisor.hand_geometry import PARAMETERS
from master_duel_advisor.regions import Calibration

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'artifacts/ash-normal-inspect-calibration-v4'
OUT=ROOT/'artifacts/ash-normal-inspect-calibration-v5'


if __name__=='__main__':
    if OUT.exists(): raise ValueError('新規v5保存先が必要です。旧版を上書きしません')
    shutil.copytree(OLD,OUT)
    config_path=OUT/'ui-bank.json'
    config=json.loads(config_path.read_text(encoding='utf-8'))
    config.update(hand_feature='raised_card_lines_v1',hand_geometry=PARAMETERS)
    config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    raw=json.loads((OUT/'calibration.json').read_text(encoding='utf-8'))
    raw['name']='Ash-connected-hand-rectangle-normal-inspect-MSS-v5'
    raw['recognition_assets']['action_evidence_detector']['sha256']=hashlib.sha256(config_path.read_bytes()).hexdigest()
    (OUT/'calibration.json').write_text(Calibration.model_validate(raw).model_dump_json(indent=2)+'\n',encoding='utf-8')
    provenance={'schema':'ash-hand-geometry-v5','new_training_images':0,'parameters':PARAMETERS,
        'diagnostics':['normal-inspect-hand-temporal-diagnostic-v4.json','normal-inspect-hand-geometry-diagnostic-v4.json'],
        'diagnostics_are_unseen_holdout':False,'scope':'既知Normal button直下のhand source形状、CID/合法種類は独立AND',
        'connection_tolerance_basis':'Hough maximum line gapと同じ8px、実edge支持の左右辺と上辺交差を同一矩形へ拘束',
        'binary_confidence_not_probability':True,'rgb_raw_score_retained_as_diagnostic':True,'input_count':0,'e2e_count':0}
    (OUT/'hand-geometry-provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(provenance,ensure_ascii=False))
