"""事故前固定派生assetからcaption方式へ更新。元フル82枚の再現とは扱いません。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from master_duel_advisor.cancel_caption import PARAMETERS,yellow_shape
from master_duel_advisor.image_io import read_image

ROOT=Path(__file__).resolve().parents[1]


def build(output):
    output=Path(output).resolve();source=ROOT/"artifacts/solo-basic-calibration-v2"
    if (output.exists() or not output.is_relative_to(ROOT.resolve())
            or output.is_relative_to((ROOT/"artifacts/baseline-tester").resolve())):
        raise ValueError("新規workspace校正先のみ。原画像配下や既存pathへ書けません")
    fixed=json.loads((ROOT/"evaluation/solo-basic-fixed-v1.json").read_text(encoding="utf-8"))
    for name,sha in {**fixed["files"],**fixed["recognition_components"]["files"]}.items():
        path=Path(name).resolve()
        if path.is_relative_to(source.resolve()) and hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            raise ValueError("元固定派生assetのhash不一致")
    layout=json.loads((source/"calibration.json").read_text(encoding="utf-8"))
    refs=[];masks=[]
    for item in layout["regions"]["action.cancel_opponent_turn_end"]["exemplars"]:
        path=source/item["image"];masks.append(yellow_shape(read_image(path)[13:27,50:128]))
        refs.append({"image":item["image"],"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                     "provenance":"fixed derived button crop created before original-frame loss"})
    prototype=(np.mean(np.stack(masks),axis=0)>=.5).astype(np.uint8)
    incident=ROOT/"evaluation/solo-cancel-training-input-incident-v1.json"
    config={"schema":"response-cancel-caption-v1","parameters":PARAMETERS,"references":refs,
        "prototype_sha256":hashlib.sha256(prototype.tobytes()).hexdigest(),"prototype_pixels":int(prototype.sum()),
        "original_training_integrity":False,"original_training_available":81,"original_training_missing":1,
        "input_incident":{"path":str(incident),"sha256":hashlib.sha256(incident.read_bytes()).hexdigest()},
        "scope":"同じcaptionの2応答のみ。意味は全文/phaseAND。色は有効表示proxy、disabled実資料なし。",
        "method_selection":"既存派生crop＋無傷81＋既知新10。新holdout/原82再現/実機E2Eではない。"}
    shutil.copytree(source,output)
    (output/"cancel-caption.json").write_text(json.dumps(config,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return config


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    build(args.output);print(args.output)
