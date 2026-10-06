"""既知DRAW PHASE帯と帯上の自分青badge。表示結果のみ、idleは生成しません。"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from .image_io import read_image

PARAMETERS={"word_bbox":[416,337,455,51],"self_blue_bbox":[970,294,32,18],
    "white_min":200,"tolerance_native_pixels":1,"word_score_min":.90,
    "blue_B_minus_R_min":40,"blue_B_minus_G_min":10,"blue_ratio_min":.15}


def white_shape(crop):
    if crop.dtype!=np.uint8 or crop.shape!=(51,455,3):
        raise ValueError("DRAW PHASE文字はnative455x51 uint8BGRのみです")
    return (np.min(crop,axis=2)>=200).astype(np.uint8)


def shape_score(prototype,candidate):
    if prototype.shape!=(51,455) or candidate.shape!=prototype.shape:
        raise ValueError("DRAW PHASE文字の固定解像度が一致しません")
    kernel=np.ones((3,3),np.uint8)
    return min(float(np.sum(prototype&cv2.dilate(candidate,kernel))/max(1,int(prototype.sum()))),
        float(np.sum(candidate&cv2.dilate(prototype,kernel))/max(1,int(candidate.sum()))))


@dataclass(frozen=True)
class DrawEvidence:
    passed: bool
    word_score: float
    self_blue_ratio: float
    config_sha256: str


class DrawOverlayDetector:
    def __init__(self,path):
        self.path=Path(path).resolve();raw=self.path.read_bytes();self.sha256=hashlib.sha256(raw).hexdigest()
        config=json.loads(raw)
        if config.get("schema")!="response-self-draw-overlay-v1" or config.get("parameters")!=PARAMETERS:
            raise ValueError("DRAW PHASE方式/尺度が固定条件と一致しません")
        refs=config.get("references",[])
        if len(refs)!=2:raise ValueError("既知失敗の方法選択派生crop2枚が必要です")
        self.files={str(self.path):self.sha256};self.stats={};features=[]
        for ref in refs:
            asset=(self.path.parent/ref["image"]).resolve()
            if not asset.is_relative_to(self.path.parent):raise ValueError("Draw派生assetが校正外です")
            data=asset.read_bytes()
            if hashlib.sha256(data).hexdigest()!=ref["sha256"]:raise ValueError("Draw派生asset hash不一致")
            features.append(white_shape(read_image(asset)));self.files[str(asset)]=ref["sha256"]
        # seq19を方法選択prototype、seq20は照合資料。新独立成功ではありません。
        self.prototype=features[0]
        if (int(self.prototype.sum())!=13903
                or hashlib.sha256(self.prototype.tobytes()).hexdigest()!=config.get("prototype_sha256")
                or shape_score(self.prototype,features[1])<.90):
            raise ValueError("Draw prototype/hash/既知比較が不一致です")
        self.files[str(Path(__file__).resolve())]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        for name in self.files:
            stat=Path(name).stat();self.stats[name]=(stat.st_size,stat.st_mtime_ns)

    def detect(self,pixels):
        for name,expected in self.stats.items():
            stat=Path(name).stat()
            if (stat.st_size,stat.st_mtime_ns)!=expected:raise ValueError("Draw overlay asset変更を検出")
        if pixels.dtype!=np.uint8 or pixels.shape!=(720,1280,3):raise ValueError("native client1280x720が必要です")
        x,y,w,h=PARAMETERS["word_bbox"];score=shape_score(self.prototype,white_shape(pixels[y:y+h,x:x+w]))
        x,y,w,h=PARAMETERS["self_blue_bbox"];blue=pixels[y:y+h,x:x+w].astype(np.int16)
        ratio=float(np.mean((blue[:,:,0]-blue[:,:,2]>=40)&(blue[:,:,0]-blue[:,:,1]>=10)))
        return DrawEvidence(score>=.90 and ratio>=.15,score,ratio,self.sha256)

    def provenance(self):
        return {"schema":"response-self-draw-overlay-v1","config_sha256":self.sha256,
            "parameters":PARAMETERS,"prototype_pixels":int(self.prototype.sum()),
            "binary_confidence":"predicate pass only, not probability","files":dict(self.files),
            "scope":"self-blue display proxy AND known DRAW PHASE word; actual opponent Draw/other phase overlay unverified"}
