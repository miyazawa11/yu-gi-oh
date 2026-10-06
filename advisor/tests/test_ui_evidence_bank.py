import json
from pathlib import Path

import numpy as np
import pytest

from master_duel_advisor.action_evidence import CaptureContext
from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import build_pipeline, close_pipeline
from master_duel_advisor.image_io import read_image
from master_duel_advisor.ui_evidence_bank import UiEvidenceBank

BASE = Path('artifacts/ash-normal-inspect-calibration-v4')
TRAIN = Path('artifacts/baseline-tester/ASH_NORMAL_INSPECT_TRAIN_v1_20261006')
OFFLINE = CaptureContext(mode='offline_saved_image', capture_source='saved_image',
    captured_at_clock='unspecified_zero_not_capture_time', frame_seq_semantics='manifest_index_not_capture_sequence')


@pytest.fixture(scope='module')
def bank():
    return UiEvidenceBank(BASE/'ui-bank.json')


def test_same_position_synonyms_do_not_reduce_margin(bank, monkeypatch):
    monkeypatch.setattr(bank, '_scores', lambda pixels, box: [.999, .998] if box[:2] == (380, 497) else [.5, .4])
    e = bank.recognize(Frame(np.zeros((720,1280,3), np.uint8), 0, 0), OFFLINE, 'solar-menu-v2')
    assert e.candidate_type == 'NORMAL_SUMMON' and e.position_margin > .49
    assert e.usable_for_input is False and {'SPECIAL_SUMMON','FLIP_SUMMON'} <= set(e.unverified_alternatives)


def test_two_different_valid_positions_remain_ambiguous(bank, monkeypatch):
    def scores(pixels, box):
        if box[:2] == (380, 497): return [.999, .5]
        if box[:2] == (420, 497): return [.5, .998]
        return [.4, .4]
    monkeypatch.setattr(bank, '_scores', scores)
    e = bank.recognize(Frame(np.zeros((720,1280,3), np.uint8), 0, 0), OFFLINE, 'solar-menu-v2')
    assert e.candidate_type is None and e.unknown_reason == 'ambiguous_position_margin'
    assert e.position_runner_up_bbox[:2] == (420, 497) and e.position_margin < .03


@pytest.mark.parametrize('version', [1,2,3])
def test_known_start_layouts_recovered_without_new_training(bank, version):
    pixels = read_image(Path(f'artifacts/baseline-tester/ASH_INSPECT_PREFLIGHT_v{version}_20261006/frame.png'))
    e = bank.recognize(Frame(pixels,0,0), OFFLINE, 'solar-menu-v2')
    assert e.candidate_type == 'NORMAL_SUMMON' and e.position_margin >= .03
    assert bank.match_hand(pixels,e.evidence_bbox)[0] == 'true'


def test_freshening_saved_image_still_rejected(bank):
    pixels = read_image(TRAIN/'menu/frame-0000.png')
    e = bank.recognize(Frame(pixels,123.,3,capture_source='saved_image'), OFFLINE, 'solar-menu-v2')
    assert e.unknown_reason == 'offline_frame_cannot_be_freshened' and e.candidate_type is None


@pytest.mark.parametrize('mutation', [
    {'hand_radius': 4}, {'minimum_score': .97}, {'minimum_position_margin': .01}, {'hand_offset': [28,82]},
])
def test_config_cannot_expand_scope_or_lower_thresholds(tmp_path, mutation):
    raw = json.loads((BASE/'ui-bank.json').read_text(encoding='utf-8')); raw.update(mutation)
    path = tmp_path/'bad.json'; path.write_text(json.dumps(raw),encoding='utf-8')
    with pytest.raises(ValueError,match='固定探索'):
        UiEvidenceBank(path)


def test_reference_hash_change_rejected(tmp_path):
    source = (BASE/'ui-bank.json').resolve()
    raw = json.loads(source.read_text(encoding='utf-8'))
    for field in ['detectors','hand_calibrations']:
        for row in raw[field]: row['path'] = str((source.parent/row['path']).resolve())
    raw['hand_calibrations'][0]['sha256'] = '0'*64
    path = tmp_path/'bad.json'; path.write_text(json.dumps(raw),encoding='utf-8')
    with pytest.raises(ValueError,match='校正hash'):
        UiEvidenceBank(path)


def test_existing_stage_and_menu_regression_no_input():
    p = build_pipeline(BASE/'calibration.json',Path('data/decks/thunder-dragon-review/cards.sqlite3'),BASE/'normal-route.json')
    try:
        stages = [('menu',TRAIN/'menu','card.menu'),('placement',TRAIN/'placement','placement.select'),
            ('post-unselected',TRAIN/'post-unselected','none'),('post-inspected',TRAIN/'post-inspected','field.inspect'),
            ('layout2',Path('artifacts/baseline-tester/ASH_NORMAL_INSPECT_LAYOUT2_TRAIN_v2_20261006/menu'),'card.menu')]
        for _,folder,expected in stages:
            for index,path in enumerate(sorted(folder.glob('frame-*.png'))):
                state = p.perception.process(Frame(read_image(path),0,index,capture_source='saved_image'))
                assert state.prompt.value == expected
                assert all(a.coordinate_proof is None for a in state.visible_actions)
        for stage in ['driver-first','ash-first','dragondark-first']:
            pixels = read_image(Path('artifacts/baseline-tester/CARD_NAME_OCR_EXPLORATION_20261006')/stage/'frame-0000.png')
            e = p.perception.inspect_detector.recognize(Frame(pixels,0,0),OFFLINE,'solar-menu-v2')
            assert e.candidate_type is None
    finally:
        close_pipeline(p)


def test_new_bank_fixed_fingerprint_and_old_profile_unchanged(bank):
    p = build_pipeline(BASE/'calibration.json',Path('data/decks/thunder-dragon-review/cards.sqlite3'),BASE/'normal-route.json')
    old = Path('artifacts/ash-normal-inspect-calibration-v3')
    q = build_pipeline(old/'calibration.json',Path('data/decks/thunder-dragon-review/cards.sqlite3'),old/'normal-route.json')
    try:
        assert isinstance(p.perception.inspect_detector, UiEvidenceBank)
        assert not isinstance(q.perception.inspect_detector, UiEvidenceBank)
        assert p.perception.recognition_components['detector']['detector_sha256'] == bank.sha256
        assert set(bank.provenance()['files']) <= set(p.perception.component_files)
        bank.assert_assets_unchanged(full_hash=True)
        p.perception.inspect_client_rect = (0,0,1280,720)
        image = read_image(Path('artifacts/baseline-tester/ASH_INSPECT_PREFLIGHT_v3_20261006/frame.png'))
        state = p.perception.process(Frame(image,0,0,capture_source='saved_image',capture_rect=(0,0,1280,720)))
        assert all(a.coordinate_proof is None for a in state.visible_actions)
    finally:
        close_pipeline(p); close_pipeline(q)


def test_bank_scope_rejected_even_if_field_mask_removed():
    p = build_pipeline(BASE/'calibration.json',Path('data/decks/thunder-dragon-review/cards.sqlite3'),BASE/'normal-route.json')
    try:
        regions = {name: region.model_copy(update={'stable_rgb_excluded_rows': []})
                   for name, region in p.perception.calibration.regions.items()}
        p.perception.calibration = p.perception.calibration.model_copy(update={'regions': regions})
        goal = p.perception.inspect_goal.model_copy(update={'card_id':'9455'})
        with pytest.raises(ValueError,match='UI bankはAsh'):
            p.perception.configure_inspect(goal,BASE)
    finally:
        close_pipeline(p)
