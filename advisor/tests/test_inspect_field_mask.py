"""比較で選んだ1maskの限定接続。既知診断画像を独立holdoutと扱いません。"""
import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import build_pipeline,close_pipeline
from master_duel_advisor.image_io import read_image
from master_duel_advisor.regions import Calibration,Region,Rect

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'artifacts/ash-normal-inspect-calibration-v3'


@pytest.mark.parametrize('rows',[list(range(5,25)),[6,6],[],[True]+list(range(7,25))])
def test_mask_configuration_cannot_expand_to_unfixed_condition(rows):
    if rows==[]:
        region=Region(rect=Rect(x=0,y=0,width=1,height=1),kind='template')
        assert 'stable_rgb_excluded_rows' not in region.model_dump(mode='json')
    else:
        with pytest.raises(ValidationError):Region(rect=Rect(x=0,y=0,width=1,height=1),kind='template',feature='stable_rgb',stable_rgb_excluded_rows=rows)


def test_field_mask_is_rejected_without_both_dedicated_regions_and_resources():
    region=Region(rect=Rect(x=0,y=0,width=1,height=1),kind='template',feature='stable_rgb',stable_rgb_excluded_rows=list(range(6,25)))
    with pytest.raises(ValidationError):Calibration(name='old-normal',regions={'fact.any':region})


def test_old_stages_and_known_diagnostic_field_are_connected_but_not_cid():
    p=build_pipeline(BASE/'calibration.json',ROOT/'data/decks/thunder-dragon-review/cards.sqlite3',BASE/'normal-route.json')
    prior=ROOT/'artifacts/baseline-tester/ASH_NORMAL_INSPECT_TRAIN_v1_20261006'
    for stage,prompt in [('placement','placement.select'),('post-unselected','none'),('post-inspected','field.inspect')]:
        for i in range(10):
            s=p.perception.process(Frame(read_image(prior/stage/f'frame-{i:04d}.png'),0,i,capture_source='saved_image'))
            assert s.prompt.value==prompt and not s.self.zones
    path=ROOT/'artifacts/baseline-tester/ASH_INSPECT_PILOT_v2_20261006/failure-current-mss/frame.png'
    s=p.perception.process(Frame(read_image(path),0,0,capture_source='saved_image'))
    assert s.prompt.value=='none' and s.facts['zone.self.monster_2.occupancy'].value=='occupied'
    assert s.facts['detail.card_id'].value is None and not s.self.zones
    assert any(a.source_region=='action.inspect_zone' for a in s.visible_actions)
    assert p.planner.filter_actions(s,s.visible_actions)==[]  # 実前提履歴なし。
    stats=p.perception.stable_statistics
    assert stats['fact.zone.self.monster_2.occupancy']['occupied']['valid_pixels']==778
    assert stats['fact.zone.self.monster_2.occupancy']['empty']['valid_pixels']==330
    close_pipeline(p)


@pytest.mark.parametrize('stage',['menu','placement'])
def test_known_empty_and_placement_remain_negative_for_occupied(stage):
    p=build_pipeline(BASE/'calibration.json',ROOT/'data/decks/thunder-dragon-review/cards.sqlite3',BASE/'normal-route.json')
    folder=ROOT/'artifacts/baseline-tester/ASH_NORMAL_INSPECT_TRAIN_v1_20261006'/stage
    for i in range(10):
        s=p.perception.process(Frame(read_image(folder/f'frame-{i:04d}.png'),0,i,capture_source='saved_image'))
        assert s.facts['zone.self.monster_2.occupancy'].value!='occupied'
        assert not any(a.source_region=='action.inspect_zone' for a in s.visible_actions)
    close_pipeline(p)
