import numpy as np

from master_duel_advisor.image_io import read_image, write_image
from master_duel_advisor.demo import generate_demo
from master_duel_advisor.cli import build_pipeline
from master_duel_advisor.evaluation import evaluate


def test_japanese_path_roundtrip(tmp_path):
    path = tmp_path / "日本語画像.png"
    pixels = np.full((12, 16, 3), 137, dtype=np.uint8)
    assert write_image(path, pixels)
    assert np.array_equal(read_image(path), pixels)
    assert read_image(tmp_path / "存在しない.png") is None


def test_demo_evaluation_in_japanese_directory(tmp_path):
    assets = generate_demo(tmp_path / "日本語の作業フォルダー")
    pipeline = build_pipeline(assets["calibration"], assets["database"])
    try:
        report = evaluate(assets["dataset"], pipeline, tmp_path / "results.json")
        assert report["errors"] == []
        assert report["game_state_exact_accuracy"] == 1
        assert not report["real_perception_gate_passed"]
    finally:
        pipeline.perception.cards.close()
