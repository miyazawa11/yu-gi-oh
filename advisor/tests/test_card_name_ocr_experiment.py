"""名前OCR実験の安全なexact alias解決。合成回帰、実機精度ではない。"""
import importlib.util
import json
from pathlib import Path
import sqlite3

import numpy as np
import pytest


@pytest.fixture
def ocr_helper():
    path = Path(__file__).parents[1] / 'scripts/benchmark_card_name_ocr.py'
    spec = importlib.util.spec_from_file_location('name_ocr_experiment', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('text,confidence,expected,reason', [
    ('太陽 電池メン', .95, '13581', None), ('太陽電池メンフー', .99, None, 'unknown_exact_alias'),
    ('太陽電池', .99, None, 'unknown_exact_alias'), ('太場電池メン', .99, None, 'unknown_exact_alias'),
    ('太陽電池メン', .89, None, 'low_ocr_confidence'), ('', 1, None, 'blank_ocr'),
])
def test_partial_fuzzy_and_low_confidence_not_confirmed(ocr_helper, text, confidence, expected, reason):
    assert ocr_helper.resolve_name(text, confidence, {'太陽電池メン': {'13581'}}) == (expected, reason)


def test_ambiguous_db_names_not_arbitrarily_resolved(ocr_helper, tmp_path):
    path = tmp_path / 'cards.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE cards(card_id TEXT,data TEXT)')
        db.executemany('INSERT INTO cards VALUES(?,?)', [('one', json.dumps({'name':'同名'})), ('two', json.dumps({'name':'同名'}))])
    aliases = ocr_helper.load_aliases(path)
    assert ocr_helper.resolve_name('同名', 1, aliases) == (None, 'ambiguous_exact_alias')


def test_tsv_segmentation_retains_minimum_word_confidence(ocr_helper):
    text = 'level\tconf\ttext\n1\t-1\t\n5\t95\t太陽\n5\t92\t電池\n5\t97\tメン\n'
    assert ocr_helper.parse_tsv(text) == ('太陽電池メン', .92)


def test_roi_cannot_read_outside_declared_local_image(ocr_helper):
    pixels = np.zeros((100,200,3), np.uint8)
    with pytest.raises(ValueError, match='ROI'): ocr_helper.render_roi(pixels, [190,10,30,20], 'raw', 3)
    assert ocr_helper.render_roi(pixels, [10,10,50,20], 'raw', 3).shape == (84,174,3)
