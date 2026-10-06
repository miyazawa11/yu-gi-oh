"""限定profile生成の合成回帰。実機画像精度・E2Eの評価ではありません。"""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from master_duel_advisor.image_io import write_image


@pytest.fixture
def generator(tmp_path):
    path = Path(__file__).parents[1] / 'scripts/build_normal_calibration.py'
    spec = importlib.util.spec_from_file_location('normal_generator_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    pixels = np.zeros((720, 1280, 3), np.uint8)
    pixels[:, :, 0] = np.arange(1280, dtype=np.uint16)[None, :] % 255
    folders = {folder: profile.get('expected_counts', {}).get(key, 20)
               for profile in module.PROFILES.values() for key, folder in profile['folders'].items()}
    for folder, count in folders.items():
        base = tmp_path / 'artifacts/baseline-tester' / folder
        base.mkdir(parents=True)
        image = base / 'fixture.png'; write_image(image, pixels)
        row = {'file': image.name, 'eligible': True, 'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}
        (base / 'manifest.json').write_text(json.dumps({'frames': [row] * count}), encoding='utf-8')
    return module


@pytest.mark.parametrize('profile,cid,goal', [('maxxc', '9455', 'normal_maxxc_center'), ('solar-slot2', '13581', 'normal_solar_center'),
                                         ('solar-slot2-v2', '13581', 'normal_solar_center')])
def test_explicit_profile_preserves_three_rules_and_local_goal(generator, tmp_path, profile, cid, goal):
    output = tmp_path / profile
    layout, book, manifest = generator.build(output, profile)
    assert len(book.rules) == 3 and all(rule.card_id == cid for rule in book.rules)
    assert all(rule.logical_action == goal and rule.logical_zone_transition.card_id == cid for rule in book.rules)
    assert book.audit_profile == 'normal_summon'
    assert all(region.threshold == .98 for region in layout.regions.values())
    assert 'self.hand_count' not in layout.regions and 'turn' not in layout.regions
    assert manifest['independent'] is False
    assert json.loads((output / 'trials.json').read_text(encoding='utf-8')) == [goal]
    if profile.startswith('solar-slot2'):
        field = layout.regions['self.zones.monster_2'].rect
        assert (field.y + field.height) * 720 < 455  # modal効果一覧開始より上の実field。
        assert layout.regions['action.normal_hand'].card_id == '13581'
    else:
        assert layout.name == 'MaxxC-same-slot-normal-summon-MSS-v1'


def test_default_profile_unchanged_after_solar_generation(generator, tmp_path):
    first = tmp_path / 'before'; after = tmp_path / 'after'
    generator.build(first)
    generator.build(tmp_path / 'solar', 'solar-slot2')
    generator.build(tmp_path / 'solar-v2', 'solar-slot2-v2')
    generator.build(after)
    for filename in ('calibration.json', 'normal-route.json', 'trials.json'):
        assert (first / filename).read_bytes() == (after / filename).read_bytes()


def test_generator_rejects_unknown_profile_and_changed_training_hash(generator, tmp_path):
    with pytest.raises(ValueError, match='未登録'): generator.build(tmp_path / 'unknown', 'unknown')
    base = generator.ROOT / 'artifacts/baseline-tester' / generator.FOLDERS['initial']
    (base / 'fixture.png').write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash不一致'): generator.build(tmp_path / 'changed')


def test_temporal_post_count_is_explicit_and_not_silently_truncated(generator, tmp_path):
    base = generator.ROOT / 'artifacts/baseline-tester/SOLAR_POST_TEMPORAL_DIAGNOSTIC_20261006'
    path = base / 'manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8')); manifest['frames'].pop()
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='訓練枚数'):
        generator.build(tmp_path / 'wrong-count', 'solar-slot2-v2')
