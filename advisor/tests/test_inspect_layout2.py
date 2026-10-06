"""追加layoutの接続/既知no-button反例。保存画像は入力許可ではありません。"""
from pathlib import Path
import json

import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import build_pipeline, close_pipeline
from master_duel_advisor.image_io import read_image

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'artifacts/ash-normal-inspect-calibration-v2'


def test_layout2_training_and_old_post_structure_remain_connected():
    report=json.loads((ROOT/'evaluation/ash-normal-inspect-training-v2.json').read_text(encoding='utf-8'))
    assert report['passed'] and report['cases']==40 and report['e2e_count']==0
    pipeline=build_pipeline(BASE/'calibration.json',ROOT/'data/decks/thunder-dragon-review/cards.sqlite3',BASE/'normal-route.json')
    assert pipeline.planner.book.audit_profile=='normal_inspect_confirmation'
    assert pipeline.perception.inspect_detector.sha256!='38ac24d4a30f0606a8d46cd4c1dfcf16c1289cf6528f8c5e844a434867f38e1f'
    close_pipeline(pipeline)


@pytest.mark.parametrize('name',['driver-first','ash-first','dragondark-first'])
def test_reviewed_opponent_detail_without_normal_ui_stays_unknown(name):
    pipeline=build_pipeline(BASE/'calibration.json',ROOT/'data/decks/thunder-dragon-review/cards.sqlite3',BASE/'normal-route.json')
    path=ROOT/'artifacts/baseline-tester/CARD_NAME_OCR_EXPLORATION_20261006'/name/'frame-0000.png'
    state=pipeline.perception.process(Frame(read_image(path),0,0,capture_source='saved_image'))
    assert not any(a.type.value=='NORMAL_SUMMON' for a in state.visible_actions)
    assert state.facts['inspect_context.summon_enabled'].value is None
    close_pipeline(pipeline)
