"""実画面の限定校正と、入力を行わないライブ計測。"""
import argparse
import time
from pathlib import Path

import numpy as np

from master_duel_advisor.cards import Card, CardDatabase
from master_duel_advisor.capture import LiveCaptureSource
from master_duel_advisor.cli import build_pipeline
from master_duel_advisor.image_io import read_image, write_image
from master_duel_advisor.pipeline import save_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--seconds", type=float, default=3)
    args = parser.parse_args()
    output = Path("artifacts/live-validation")
    output.mkdir(parents=True, exist_ok=True)
    calibration_path = output / "calibration.json"
    database = output / "cards.sqlite3"
    if args.prepare:
        regions = {}
        sources = {"DRAW": "live-calibration-source.png", "MAIN1": "live-main1-source.png",
                   "BATTLE": "live-validation-001.png"}
        images = {label: read_image(Path("artifacts") / file) for label, file in sources.items()}
        preserved_battle = output / "battle-source-preserved.png"
        if preserved_battle.exists():
            images["BATTLE"] = read_image(preserved_battle)
        opponent_sample = output / "opponent-main1-training.png"
        if opponent_sample.exists():
            images["OPP_MAIN1"] = read_image(opponent_sample)
        if any(img is None or img.mean() < 1 for img in images.values()):
            raise ValueError("校正画像がありません、または黒画像です")
        def region(name, box, kind, examples, card_id=None):
            x,y,w,h = box
            exemplars = []
            for index, (label, phase) in enumerate(examples):
                img = images[phase][y:y+h, x:x+w]
                filename = name.replace(".", "_") + "_" + label + f"_{index}.png"
                write_image(output / filename, img)
                exemplars.append({"label": label, "image": filename})
            regions[name] = {"rect": {"x": x/1280, "y": y/800, "width": w/1280, "height": h/800},
                             "kind": kind, "threshold": .98, "margin": .02,
                             "exemplars": exemplars, "card_id": card_id}
        phase_examples = [(p,p) for p in sources]
        player_examples = [("self", p) for p in sources]
        lp_examples = [("8000", "BATTLE")]
        if "OPP_MAIN1" in images:
            phase_examples.append(("MAIN1", "OPP_MAIN1"))
            player_examples.append(("opponent", "OPP_MAIN1"))
            lp_examples.append(("7800", "OPP_MAIN1"))
        region("phase", (953,346,73,25), "template", phase_examples)
        region("turn_player", (948,371,81,20), "template", player_examples)
        region("self.lp", (151,704,103,25), "template", [("8000", "BATTLE")])
        region("opponent.lp", (1066,78,108,25), "template", lp_examples)
        region("self.zones.monster_1", (498,319,55,62), "card", [("13923", "BATTLE")])
        region("action.colossus_select", (488,308,80,97), "action",
               [("SELECT_CARD", "BATTLE")], "13923")
        save_json(calibration_path, {"name": "実画面・ターン2の限定検証",
                                    "viewport": {"x": 0,"y": 0,"width": 1,"height": 1},
                                    "aspect_ratio": 1.6, "regions": regions})
        db = CardDatabase(database)
        db.import_cards([Card(card_id="13923", name="超雷龍－サンダー・ドラゴン", type="monster")])
        db.close()
        save_json(output / "plan-book.json", {"recipes": [{"id": "battle-select",
            "goal": "超雷龍の攻撃候補を開いて確認する", "requires": [
                {"zone_prefix": "monster_", "card_id": "13923"}],
            "steps": [{"description": "攻撃可能な超雷龍を選択する", "type": "SELECT_CARD",
                       "source_region": "action.colossus_select", "card_id": "13923",
                       "phases": ["BATTLE"]}]}]})
        return
    if not 0 < args.seconds <= 30:
        raise ValueError("計測時間は0より大きく30秒以下で指定してください")
    pipeline = build_pipeline(calibration_path, database, output / "plan-book.json")
    capture = LiveCaptureSource("mss", (-1920,785,-640,1585), 20)
    started = time.perf_counter()
    timings, snapshots = [], []
    try:
        while time.perf_counter() - started < args.seconds:
            begin = time.perf_counter()
            frame = capture.read()
            read_ms = (time.perf_counter()-begin)*1000
            if frame is None or frame.pixels.mean() < 1:
                raise ValueError("画面を取得できません、または黒画像です")
            result = pipeline.process(frame, read_ms)
            timings.append(result["metrics"])
            if len(snapshots) < 3:
                name = f"holdout-{len(snapshots)}.png"
                write_image(output / name, frame.pixels)
                save_json(output / name.replace(".png", ".json"), result)
                snapshots.append(name)
            save_json(output / "latest.json", result)
            time.sleep(max(0, .05-(time.perf_counter()-begin)))
    finally:
        capture.close()
        pipeline.perception.cards.close()
    elapsed = time.perf_counter()-started
    report = {"mode": "live_read_only", "frames": len(timings), "elapsed_seconds": elapsed,
              "received_fps": len(timings)/elapsed, "snapshots": snapshots,
              "metrics_p95_ms": {key: float(np.percentile([t[key] for t in timings],95))
                                 for key in ["capture_read_ms","perception_ms","decision_ms","total_compute_ms"]},
              "actual_clicks": 0, "recognition_accuracy": None,
              "limitations": ["同一対戦画面の限定校正。一般的な認識精度は未評価", "入力とクリック間隔は未計測"]}
    save_json(output / "report.json", report)
    print(report)


if __name__ == "__main__":
    main()
