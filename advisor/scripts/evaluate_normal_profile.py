"""固定通常召喚profileの画像認識検証。入力なし、訓練と独立評価を区別。"""
from pathlib import Path
import argparse
import hashlib
import json
import time
import numpy as np

from master_duel_advisor.capture import Frame
from master_duel_advisor.cards import CardDatabase
from master_duel_advisor.image_io import read_image
from master_duel_advisor.perception import Perception, fingerprint
from master_duel_advisor.regions import load_calibration
from master_duel_advisor.strategy_rules import load_planner


def evaluate(calibration, database, route, samples):
    layout = load_calibration(calibration)
    planner = load_planner(route)
    cid = planner.book.rules[0].card_id
    cards = CardDatabase(database)
    try:
        if cards.get(cid) is None:
            raise ValueError('宣言CIDがローカルカードDBにありません')
        perception = Perception(layout, calibration.parent, cards)
        rows = []
        for sequence, sample in enumerate(samples, 1):
            path = Path(sample['path'])
            if hashlib.sha256(path.read_bytes()).hexdigest() != sample['sha256']:
                raise ValueError('評価画像hash不一致: ' + str(path))
            pixels = read_image(path)
            if pixels is None or pixels.shape != (720, 1280, 3):
                raise ValueError('client 1280x720画像が必要です')
            perception._cache.clear()  # 各画像を独立に照合し、前画像の認識を再使用しない。
            started = time.perf_counter()
            state = perception.process(Frame(pixels, time.monotonic(), sequence))
            elapsed = (time.perf_counter() - started) * 1000
            allowed = planner.filter_actions(state, state.visible_actions)
            start_allowed = any(a.source_region == 'action.normal_hand' for a in allowed)
            occ = state.facts['zone.self.monster_2.occupancy']
            field = state.self.zones['monster_2']
            post_evidence = occ.value == 'occupied' and field.value is not None and field.value.card_id == cid
            raw_scores = {}
            for name in ('fact.zone.self.monster_2.occupancy', 'self.zones.monster_2'):
                matcher = perception.matchers[name]
                descriptor = fingerprint(matcher.region.rect.crop(pixels))
                raw_scores[name] = {label: float(1-np.mean(np.abs(descriptor-prototype)[mask]))
                                    for label, prototype, mask in matcher.stable_profiles}
            label = sample['label']
            expected_action = {'initial': 'action.normal_hand', 'menu': 'action.normal_summon',
                               'placement': 'action.normal_place'}.get(label)
            action = next((a for a in state.visible_actions if a.source_region == expected_action), None)
            rule = planner.rule_for(action) if action else None
            positive = action is not None and rule is not None and not rule.missing(state, .98)
            passed = (start_allowed and not post_evidence if label == 'initial' else
                      positive and not start_allowed and not post_evidence if label in {'menu', 'placement'} else
                      post_evidence and not start_allowed if label == 'post' else
                      not start_allowed and not post_evidence if label in {'negative', 'pending_post'} else False)
            rows.append({'path': str(path), 'sha256': sample['sha256'], 'label': label, 'passed': passed,
                         'start_allowed': start_allowed, 'post_evidence': post_evidence, 'recognition_ms': elapsed,
                         'raw_scores': raw_scores,
                         'state': state.model_dump(mode='json')})
        return {'mode': 'image-only-no-input', 'input_count': 0, 'real_e2e_samples': 0,
                'card_id': cid, 'samples': len(rows), 'passed': all(row['passed'] for row in rows),
                'calibration_sha256': hashlib.sha256(calibration.read_bytes()).hexdigest(),
                'route_sha256': hashlib.sha256(route.read_bytes()).hexdigest(),
                'stable_statistics': perception.stable_statistics, 'rows': rows,
                'limitations': ['post_evidenceは占有とCIDの画像証拠のみ。実送信・選択履歴を含む目的成功ではない',
                                '訓練画像の成功を独立holdout精度や実機E2Eとして扱わない']}
    finally:
        cards.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calibration', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--route', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--stage', choices=['initial', 'menu', 'placement', 'post', 'negative', 'pending_post'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    if 'training' in manifest:
        samples = manifest['training']
        independent = False
    else:
        if args.stage is None:
            raise ValueError('frame manifestには目視で確認した--stageを指定してください')
        samples = [{'path': str(args.manifest.parent / row['file']), 'sha256': row['sha256'], 'label': args.stage}
                   for row in manifest['frames'] if row.get('eligible') is True]
        if len(samples) != len(manifest['frames']) or not samples:
            raise ValueError('不適合frameを黙って評価から除外しません')
        independent = None  # 独立性は収集日時と校正固定後の証拠を別途レビュー。
    result = evaluate(args.calibration, args.database, args.route, samples)
    result['independent'] = independent
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key not in {'rows', 'stable_statistics'}}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
