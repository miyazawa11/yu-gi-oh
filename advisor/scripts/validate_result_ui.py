"""実対戦終了画面の限定校正・認識。入力は行いません。"""
import time
import argparse
from pathlib import Path

from master_duel_advisor.capture import Frame
from master_duel_advisor.cards import CardDatabase
from master_duel_advisor.cli import build_pipeline
from master_duel_advisor.image_io import read_image, write_image
from master_duel_advisor.pipeline import save_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image",type=Path,default=Path("artifacts/result-ui-validation/source.png"))
    args = parser.parse_args()
    out = Path("artifacts/result-ui-validation")
    out.mkdir(parents=True,exist_ok=True)
    pixels = read_image(args.image)
    if pixels is None or pixels.mean() < 1:
        raise ValueError("実画面が取得されていません")
    write_image(out / "source.png",pixels)
    regions = {}
    for name,box,label,kind in [
        ("ui.prompt",(571,501,139,32),"duel_result","template"),
        ("action.result_ok",(473,660,334,37),"CONFIRM","action")]:
        x,y,w,h = box
        file = name.replace(".","_")+".png"
        write_image(out/file,pixels[y:y+h,x:x+w])
        regions[name] = {"rect":{"x":x/1280,"y":y/800,"width":w/1280,"height":h/800},
                         "kind":kind,"threshold":.99,"margin":.02,
                         "exemplars":[{"label":label,"image":file}]}
    save_json(out/"calibration.json",{"name":"実対戦終了のOK限定校正","aspect_ratio":1.6,"regions":regions})
    save_json(out/"ui-rules.json",{"rules":[{"prompt":"duel_result","type":"CONFIRM","source_region":"action.result_ok"}]})
    CardDatabase(out/"cards.sqlite3").close()
    pipeline = build_pipeline(out/"calibration.json",out/"cards.sqlite3",ui_rules=out/"ui-rules.json")
    try:
        result = pipeline.process(Frame(pixels=pixels,sequence=0,captured_at=time.monotonic()))
        save_json(out/"recognition.json",result)
        assert result["recommendation"]["action"]["source_region"] == "action.result_ok"
        print(result["recommendation"])
        print(result["metrics"])
    finally:
        pipeline.perception.cards.close()


if __name__ == "__main__": main()
