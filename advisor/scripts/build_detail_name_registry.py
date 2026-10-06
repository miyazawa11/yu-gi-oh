"""3枚の確認済み名前参照を固定します。"""
from pathlib import Path
import hashlib
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from master_duel_advisor.detail_name_registry import ROI, SHAPE, MIN_SCORE, MIN_MARGIN
from master_duel_advisor.image_io import read_image, write_image

REFERENCES = {
    "9455": ("増殖するG", "artifacts/baseline-tester/MAXXC_MENU_TRAIN_v1_full/frame-0000.png"),
    "13581": ("太陽電池メン", "artifacts/baseline-tester/MAXXC_CURRENT_HAND_TRAIN_20261006/solar-menu/frame-0000.png"),
    "12950": ("灰流うらら", "artifacts/baseline-tester/CARD_NAME_OCR_EXPLORATION_20261006/ash-first/frame-0000.png"),
}


def build(output: Path):
    output.mkdir(parents=True, exist_ok=False)
    refs = []
    for cid, (name, source) in REFERENCES.items():
        path = Path(source)
        pixels = read_image(str(path))
        if pixels is None or pixels.shape != SHAPE:
            raise ValueError(f"参照元サイズ不正: {path}")
        x, y, w, h = ROI
        image = output / f"{cid}.png"
        write_image(str(image), pixels[y:y+h, x:x+w])
        refs.append({"cid": cid, "japanese_name": name, "image": image.name,
                     "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                     "source_image": source, "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "identity_source": f"https://www.db.yugioh-card.com/yugiohdb/card_search.action?ope=2&cid={cid}&request_locale=ja"})
    data = {"schema": "detail-name-registry-v1", "namespace": "konami",
            "source": "master_duel_selected_detail_name", "roi": list(ROI), "capture_shape": list(SHAPE),
            "feature": "bgr_area_64x32_mae", "minimum_score": MIN_SCORE, "minimum_margin": MIN_MARGIN,
            "references": refs, "scope": "selected_detail_only"}
    path = output / "registry.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    build(parser.parse_args().output)
