"""独立した合成正解ラベルと再生データを生成します。実ゲームのデータではありません。"""
from pathlib import Path

import cv2
import numpy as np

from .cards import Card, CardDatabase
from .pipeline import save_json


def generate_demo(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    templates = directory/"templates"
    templates.mkdir(exist_ok=True)
    specs = {
        "self.lp": (0, 0, ["8000", "5200"]),
        "opponent.lp": (1, 0, ["8000", "5200"]),
        "turn_player": (2, 0, ["self", "opponent"]),
        "phase": (3, 0, ["MAIN1", "BATTLE"]),
        "turn": (0, 1, ["1", "2"]),
        "self.hand_count": (1, 1, ["5", "4"]),
        "self.zones.monster_1": (2, 1, ["demo-alpha", "demo-beta"]),
        "action.primary": (3, 1, ["NORMAL_SUMMON", "ATTACK", "ACTIVATE"]),
    }
    tile_w, tile_h = 160, 90
    exemplar_images = {}
    regions = {}
    rng = np.random.default_rng(12345)
    for name, (col, row, labels) in specs.items():
        exemplars = []
        for label in labels:
            # 独立したランダム模様で未知の場面も含めて区別します。
            patch = rng.integers(20, 220, size=(9, 16, 3), dtype=np.uint8)
            tile = cv2.resize(patch, (tile_w, tile_h), interpolation=cv2.INTER_NEAREST)
            cv2.putText(tile, label[:15], (7, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)
            filename = f"{name.replace('.', '_')}_{label}.png"
            cv2.imwrite(str(templates/filename), tile)
            exemplars.append({"label": label, "image": "templates/"+filename})
            exemplar_images[name, label] = tile
        regions[name] = {"rect": {"x": col/4, "y": row/4, "width": 0.25, "height": 0.25}, "kind": "card" if ".zones." in name else "action" if name.startswith("action.") else "template", "threshold": 0.97, "margin": 0.03, "exemplars": exemplars}
    calibration = directory/"calibration.json"
    save_json(calibration, {"name": "合成データ専用 — Master Duel の座標ではありません", "regions": regions})
    db = CardDatabase(directory/"cards.sqlite3")
    cards = [Card(card_id="demo-alpha", name="合成カード・アルファ", type="monster", atk=300), Card(card_id="demo-beta", name="合成カード・ベータ", type="monster", atk=500)]
    db.import_cards(cards)
    db.close()
    save_json(directory/"cards.json", [card.model_dump(mode="json") for card in cards])
    scenarios = [
        {"self.lp": "8000", "opponent.lp": "8000", "turn_player": "self", "phase": "MAIN1", "turn": "1", "self.hand_count": "5", "self.zones.monster_1": "demo-alpha", "action.primary": "NORMAL_SUMMON"},
        {"self.lp": "8000", "opponent.lp": "5200", "turn_player": "self", "phase": "BATTLE", "turn": "2", "self.hand_count": "4", "self.zones.monster_1": "demo-beta", "action.primary": "ATTACK"},
        {name: None for name in specs},
        {"self.lp": "5200", "opponent.lp": "8000", "turn_player": "opponent", "phase": "MAIN1", "turn": "2", "self.hand_count": "4", "self.zones.monster_1": "demo-alpha", "action.primary": "ACTIVATE"},
    ]
    video = directory/"recording.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (640, 360))
    if not writer.isOpened():
        raise RuntimeError("OpenCV の MP4 保存機能を利用できません")
    samples = []
    try:
        for index, scenario in enumerate(scenarios):
            frame = np.zeros((360, 640, 3), np.uint8)
            expected = {}
            for name, label in scenario.items():
                col, row, _ = specs[name]
                tile = exemplar_images[name, label] if label is not None else np.zeros((tile_h, tile_w, 3), np.uint8)
                frame[row*tile_h:(row+1)*tile_h, col*tile_w:(col+1)*tile_w] = tile
                if name.startswith("action."):
                    continue
                if label is None:
                    expected[name] = None
                elif ".zones." in name:
                    expected[name] = {"card_id": label, "name": "合成カード・アルファ" if label == "demo-alpha" else "合成カード・ベータ"}
                elif name in {"phase", "turn_player"}:
                    expected[name] = label
                else:
                    expected[name] = int(label)
            image = f"frame_{index}.png"
            cv2.imwrite(str(directory/image), frame)
            action = scenario["action.primary"]
            samples.append({"image": image, "expected": expected, "actions": [action] if action else [], "recommendation": action})
            for _ in range(3):
                writer.write(frame)
    finally:
        writer.release()
    dataset = directory/"dataset.json"
    save_json(dataset, {"kind": "synthetic", "samples": samples})
    return {"calibration": calibration, "database": directory/"cards.sqlite3", "dataset": dataset, "video": video}
