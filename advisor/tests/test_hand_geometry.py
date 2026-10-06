import json
from pathlib import Path

import numpy as np
import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import build_pipeline, close_pipeline
from master_duel_advisor.hand_geometry import connected_rectangle, recognize_hand_geometry, extend_vertical_with_edges, PARAMETERS_SHA256
from master_duel_advisor.image_io import read_image
from master_duel_advisor.models import GameState
from test_inspect_profile import inspect_case

BASE=Path('artifacts/ash-normal-inspect-calibration-v5')
TRAIN=Path('artifacts/baseline-tester/ASH_NORMAL_INSPECT_TRAIN_v1_20261006')


@pytest.mark.parametrize('top', [
    [430,578,516,578],
    [480,578,566,578],  # 近隣別矩形の上辺
    [430,605,516,605],  # せり上がっていない手札の高さ
    [430,558,516,558],  # 縦辺上端と接続しない
])
def test_top_must_connect_both_sides_of_same_raised_rectangle(top):
    selected=connected_rectangle([[425,578,425,706],[511,580,511,706]],[top],(380,497))
    assert bool(selected) == (top == [430,578,516,578])


def test_two_nearby_rectangles_cannot_supply_disconnected_top():
    lines=[[425,578,425,706],[511,580,511,706],[545,578,545,706],[631,580,631,706]]
    assert connected_rectangle(lines,[[550,578,636,578]],(380,497)) is None
    assert connected_rectangle(lines[:1],[[430,578,516,578]],(380,497)) is None


def test_projected_extension_requires_real_edges_and_fixed_gap():
    edges=np.zeros((150,135),np.uint8);roi=(400,567,135,150)
    edges[10:40,25]=255;edges[20:28,25]=0
    extended=extend_vertical_with_edges([[425,599,425,706]],edges,roi)
    assert extended[0][1]==577  # 実edgeと最大8連続欠落をつなぐ
    edges[20:29,25]=0
    assert extend_vertical_with_edges([[425,599,425,706]],edges,roi)[0][1]==596
    assert extend_vertical_with_edges([[425,599,425,706]],np.zeros_like(edges),roi)[0][1]==599


@pytest.mark.parametrize('pixels,box', [
    (np.zeros((720,1280,3),np.float32),(380,497,74,79)),
    (np.zeros((720,1279,3),np.uint8),(380,497,74,79)),
    (np.zeros((720,1280,3),np.uint8),(315,497,74,79)),
    (np.zeros((720,1280,3),np.uint8),(380.5,497,74,79)),
])
def test_invalid_geometry_capture_or_anchor_rejected(pixels,box):
    with pytest.raises(ValueError): recognize_hand_geometry(pixels,box)


def test_known_temporal_scenes_and_post_classes_no_input():
    p=build_pipeline(BASE/'calibration.json',Path('data/decks/thunder-dragon-review/cards.sqlite3'),BASE/'normal-route.json')
    try:
        folders=[Path('artifacts/baseline-tester/ASH_INSPECT_MENU_TEMPORAL_v4_20261006/menu'),TRAIN/'menu',
                 Path('artifacts/baseline-tester/ASH_NORMAL_INSPECT_LAYOUT2_TRAIN_v2_20261006/menu')]
        for folder in folders:
            for i,path in enumerate(sorted(folder.glob('frame-*.png'))):
                s=p.perception.process(Frame(read_image(path),0,i,capture_source='saved_image'))
                assert s.prompt.value=='card.menu', str(path)
                assert s.facts['inspect_context.hand_selected'].source=='geometry:'+PARAMETERS_SHA256
                assert any(a.type.value=='NORMAL_SUMMON' for a in s.visible_actions)
                assert all(a.coordinate_proof is None for a in s.visible_actions)
                diagnostic=s.facts['inspect_context.hand_source_diagnostic']
                assert diagnostic.confidence==0 and json.loads(diagnostic.value)['rgb_not_used_as_gate']
        for stage in ['post-unselected','post-inspected']:
            for path in sorted((TRAIN/stage).glob('frame-*.png')):
                geometry=recognize_hand_geometry(read_image(path),(380,497,74,79))
                assert geometry['passed'] is False
        for stage in ['driver-first','ash-first','dragondark-first']:
            image=read_image(Path('artifacts/baseline-tester/CARD_NAME_OCR_EXPLORATION_20261006')/stage/'frame-0000.png')
            s=p.perception.process(Frame(image,0,0,capture_source='saved_image'))
            assert not any(a.type.value=='NORMAL_SUMMON' for a in s.visible_actions)
        image=read_image(Path('artifacts/baseline-tester/MAXXC_CURRENT_HAND_TRAIN_20261006/solar-menu/frame-0000.png'))
        s=p.perception.process(Frame(image,0,0,capture_source='saved_image'))
        assert s.facts['detail.card_id'].value=='13581'
        assert not any(a.type.value=='NORMAL_SUMMON' for a in s.visible_actions)
    finally: close_pipeline(p)


@pytest.mark.parametrize('change',['none','template_source','wrong_hash','unknown','stale'])
def test_goal_requires_new_geometry_source_and_keeps_identity_receipts(tmp_path,change):
    t,r,s=inspect_case(tmp_path)
    t.metadata['recognition_components']['detector'].update(hand_feature='raised_card_lines_v1',hand_geometry_sha256=PARAMETERS_SHA256)
    hand=t.active['steps'][0]['inspect_before']['facts']['inspect_context.hand_selected']
    hand['source']='geometry:'+PARAMETERS_SHA256
    if change=='template_source': hand['source']='template:fixture'
    elif change=='wrong_hash': hand['source']='geometry:'+'0'*64
    elif change=='unknown': hand.update(value=None,confidence=0)
    elif change=='stale': hand['observed_at']=.5
    assert t.goal_confirmed(r,s)==(change=='none')


def test_geometry_config_change_and_saved_freshening_rejected(tmp_path):
    from master_duel_advisor.ui_evidence_bank import UiEvidenceBank
    source=(BASE/'ui-bank.json').resolve();raw=json.loads(source.read_text(encoding='utf-8'))
    for field in ['detectors','hand_calibrations']:
        for row in raw[field]:row['path']=str((source.parent/row['path']).resolve())
    raw['hand_geometry']['connection_tolerance']=9
    path=tmp_path/'bad.json';path.write_text(json.dumps(raw),encoding='utf-8')
    with pytest.raises(ValueError,match='固定パラメータ'):UiEvidenceBank(path)
    p=build_pipeline(BASE/'calibration.json',Path('data/decks/thunder-dragon-review/cards.sqlite3'),BASE/'normal-route.json')
    try:
        p.perception.inspect_client_rect=(0,0,1280,720)
        image=read_image(TRAIN/'menu/frame-0000.png')
        s=p.perception.process(Frame(image,99999,0,capture_source='saved_image',capture_rect=(0,0,1280,720)))
        assert not any(a.type.value=='NORMAL_SUMMON' for a in s.visible_actions)
    finally:close_pipeline(p)
