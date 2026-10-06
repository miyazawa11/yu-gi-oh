"""既知失敗runtime2枚を方法選択派生assetへ。元frame・旧校正は変更しません。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from master_duel_advisor.draw_outcome import PARAMETERS,white_shape
from master_duel_advisor.image_io import read_image,write_image

ROOT=Path(__file__).resolve().parents[1]


def build(output):
    output=Path(output).resolve();source=ROOT/"artifacts/solo-basic-calibration-v3"
    run=ROOT/"artifacts/baseline-tester/SOLO_END_PILOT_v2_20261006/screenshots"
    inputs={source,*(run/f"verify-failure-0000-{role}-seq{seq}.png" for role,seq in [("last_recognized",19),("last_captured",20)])}
    if (output.exists() or not output.is_relative_to(ROOT.resolve())
            or output.is_relative_to((ROOT/"artifacts/baseline-tester").resolve())
            or any(output==p.resolve() or output.is_relative_to(p.resolve()) for p in inputs)):
        raise ValueError("新規workspace校正先かつ全入力と非重複のみです")
    fixed=json.loads((ROOT/"evaluation/solo-basic-fixed-v2.json").read_text(encoding="utf-8"))
    for name,sha in {**fixed["files"],**fixed["recognition_components"]["files"]}.items():
        path=Path(name).resolve()
        if path.is_relative_to(source.resolve()) and hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            raise ValueError("旧校正asset固定hash不一致")
    refs=[];crops=[];x,y,w,h=PARAMETERS["word_bbox"]
    for role,seq in [("last_recognized",19),("last_captured",20)]:
        original=run/f"verify-failure-0000-{role}-seq{seq}.png"
        side=json.loads(original.with_suffix(".json").read_text(encoding="utf-8"))
        sha=hashlib.sha256(original.read_bytes()).hexdigest()
        if sha!=side["image_sha256"] or side["sequence"]!=seq:raise ValueError("原runtime frame/hash/seq不一致")
        crops.append(read_image(original)[y:y+h,x:x+w].copy())
        refs.append({"image":f"draw-overlay-method-selection-seq{seq}.png","original_runtime":str(original),
            "original_sha256":sha,"original_sequence":seq,"original_captured_at_monotonic":side["captured_at_monotonic"],
            "provenance":"known failed runtime method selection; not independent holdout or successful endpoint"})
    shutil.copytree(source,output)
    for ref,crop in zip(refs,crops):
        asset=(output/ref["image"]).resolve()
        if asset.exists() or asset in {p.resolve() for p in inputs}:raise ValueError("Draw出力assetが既存/入力と衝突")
        if not write_image(asset,crop):raise OSError("Draw派生crop保存失敗")
        ref["sha256"]=hashlib.sha256(asset.read_bytes()).hexdigest()
    config={"schema":"response-self-draw-overlay-v1","parameters":PARAMETERS,"references":refs,
        "prototype_sha256":hashlib.sha256(white_shape(crops[0]).tobytes()).hexdigest(),
        "scope":"overlay-free Draw unchanged OR overlay word+self-blue+modal-absent; idle not asserted",
        "unverified":"actual opponent Draw and other large phase overlay samples unavailable",
        "original_training_integrity":False,"original_training_available":81,"original_training_missing":1}
    (output/"draw-overlay.json").write_text(json.dumps(config,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return config


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();build(args.output);print(args.output)
