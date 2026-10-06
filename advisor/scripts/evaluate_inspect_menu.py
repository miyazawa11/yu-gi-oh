"""固定後の同scene新MSS menu10枚をoffline0で評価。実入力/E2E/新scene汎化ではありません。"""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import build_pipeline, close_pipeline
from master_duel_advisor.image_io import read_image

ROOT = Path(__file__).resolve().parents[1]


def evaluate(manifest_path, fixed_path, base):
    fixed = json.loads(fixed_path.read_text(encoding='utf-8'))
    for name, sha in {**fixed['recognition_components']['files'], **fixed['files']}.items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != sha:
            raise ValueError('固定source/asset/helper hash不一致: '+name)
    frozen = datetime.fromisoformat(fixed['frozen_at_utc'])
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if (manifest.get('capture_source') != 'mss' or len(manifest['frames']) != 10
            or not all(r['eligible'] for r in manifest['frames'])):
        raise ValueError('固定後の適合実MSS10枚が必要です')
    pipeline = build_pipeline(base/'calibration.json', ROOT/'data/decks/thunder-dragon-review/cards.sqlite3', base/'normal-route.json')
    rows = []
    try:
        for index, row in enumerate(manifest['frames']):
            if (type(row.get('captured_at_monotonic')) not in (int, float)
                    or not math.isfinite(row['captured_at_monotonic']) or row['captured_at_monotonic'] <= 0
                    or type(row.get('capture_sequence')) is not int or row['capture_sequence'] < 0
                    or datetime.fromisoformat(row['capture_start_utc']) <= frozen):
                raise ValueError('固定後の元取得時計/sequenceが必要です')
            path = (manifest_path.parent/row['file']).resolve()
            if (not path.is_relative_to(manifest_path.parent.resolve())
                    or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']):
                raise ValueError('新取得画像path/hash不一致')
            state = pipeline.perception.process(Frame(read_image(path), 0, index, capture_source='saved_image'))
            f = state.facts
            passed = (state.phase.value == 'MAIN1' and state.turn_player.value == 'self'
                and state.prompt.value == 'card.menu' and state.animation.value is False and state.terminal.value is False
                and f['detail.card_id'].value == '12950' and f['inspect_context.hand_selected'].value == 'true'
                and f['inspect_context.summon_enabled'].value == 'true'
                and f['zone.self.monster_2.occupancy'].value == 'empty'
                and any(a.type.value == 'NORMAL_SUMMON' and a.card_id == '12950' for a in state.visible_actions))
            rows.append({'index': index, 'passed': passed, 'original_capture': row,
                'recognition_observed_at': 0, 'offline_coordinate_proof_absent': all(a.coordinate_proof is None for a in state.visible_actions),
                'state': state.model_dump(mode='json')})
        return {'schema': 'ash-menu-temporal-recognition-v4', 'passed': all(r['passed'] for r in rows),
            'cases': len(rows), 'input_count': 0, 'e2e_count': 0, 'training_used': False,
            'source_sha256': fixed['source_sha256'], 'manifest': str(manifest_path),
            'original_manifest_metadata': {k:v for k,v in manifest.items() if k != 'frames'},
            'evaluation_capture_context': 'offline_saved_image_observed_at_zero',
            'scope': '同scene固定後時間的再取得、offline候補をlive入力許可へ昇格しない', 'rows': rows}
    finally:
        close_pipeline(pipeline)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--fixed', type=Path, default=ROOT/'evaluation/normal-inspect-fixed-v4.json')
    parser.add_argument('--profile-base', type=Path, default=ROOT/'artifacts/ash-normal-inspect-calibration-v4')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.manifest, args.fixed, args.profile_base)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k in ['passed','cases','input_count','e2e_count']}))
    raise SystemExit(0 if report['passed'] else 1)
