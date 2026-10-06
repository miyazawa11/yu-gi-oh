"""v3を保持して既存UI参照bankのv4を作成。新画像・手札数別の訓練は追加しません。"""
import hashlib
import json
import os
from pathlib import Path
import shutil

from master_duel_advisor.action_evidence import SEARCH
from master_duel_advisor.regions import Calibration, RecognitionResource

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT/'artifacts/ash-normal-inspect-calibration-v3'
OUT = ROOT/'artifacts/ash-normal-inspect-calibration-v4'


def build():
    if OUT.exists():
        raise ValueError('新規v4保存先が必要です。既存版を上書きしません')
    shutil.copytree(OLD, OUT)
    config_path = OUT/'ui-bank.json'
    def entry(path):
        return {'path': os.path.relpath(path, config_path.parent),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    config = {'schema': 'normal-inspect-ui-bank-v1', 'profile_id': 'solar-menu-v2',
        'search': SEARCH, 'minimum_score': .98, 'minimum_position_margin': .03,
        'hand_offset': [27, 82], 'hand_radius': 3, 'hand_size': [18, 112], 'usable_for_input': False,
        'detectors': [entry(ROOT/'evaluation/action-evidence-detector-v1.json'),
                      entry(OUT/'readonly-detector-support/detector.json')],
        'hand_calibrations': [entry(ROOT/'artifacts/ash-normal-inspect-calibration-v1/calibration.json'),
                              entry(OLD/'calibration.json')]}
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    raw = json.loads((OUT/'calibration.json').read_text(encoding='utf-8'))
    raw['name'] = 'Ash-existing-UI-reference-bank-normal-inspect-MSS-v4'
    raw['recognition_assets']['action_evidence_detector'] = RecognitionResource(
        path='ui-bank.json', sha256=hashlib.sha256(config_path.read_bytes()).hexdigest()).model_dump(mode='json')
    (OUT/'calibration.json').write_text(Calibration.model_validate(raw).model_dump_json(indent=2)+'\n', encoding='utf-8')
    provenance = {'schema': 'ash-ui-bank-v4', 'existing_source': str(OLD),
        'new_training_images': 0, 'method_selection_is_holdout': False,
        'diagnostics': ['normal-inspect-hand5-diagnostic-v3.json', 'normal-inspect-prototype-bank-diagnostic-v3.json'],
        'hand_radius_basis': '既存UIの3px精探索と同一relative offset、旧/新cropの1px偏差、既知負例比較',
        'scope': 'Ash normal inspect限定。Special/Flip/disabledは未検証、入力許可は別runtime guard',
        'bank_sha256': hashlib.sha256(config_path.read_bytes()).hexdigest(), 'input_count': 0, 'e2e_count': 0}
    (OUT/'ui-bank-provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return provenance


if __name__ == '__main__':
    print(json.dumps(build(), ensure_ascii=False))
