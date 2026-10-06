"""固定応答UIの黄色Cancel文字形状。CID・prompt・発動最善判断は生成しません。"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from .image_io import read_image

PARAMETERS={"caption_bbox":[506,674,78,14],"click_bbox":[456,661,178,40],"click_point":[545,681],
    "r_min":160,"g_min":160,"b_max":100,"tolerance_native_pixels":1,"acceptance_score":.85}


def diagnostic_output_path(path, input_paths, evaluation_root):
    """診断書き込み先を先に固定し、入力との衝突・上書きを拒否します。"""
    target=Path(path).resolve();root=Path(evaluation_root).resolve()
    if not target.is_relative_to(root) or target in {Path(p).resolve() for p in input_paths} or target.exists():
        raise ValueError("診断出力は新規evaluation配下かつ全入力pathと非重複にしてください")
    return target


def yellow_shape(crop):
    if crop.dtype!=np.uint8 or crop.shape!=(14,78,3):
        raise ValueError("Cancel captionはnative uint8BGR78x14のみです")
    return ((crop[:,:,2]>=160)&(crop[:,:,1]>=160)&(crop[:,:,0]<=100)).astype(np.uint8)


def tolerant_shape_score(prototype,candidate):
    if prototype.shape!=(14,78) or candidate.shape!=prototype.shape:
        raise ValueError("文字形状の固定解像度が一致しません")
    kernel=np.ones((3,3),np.uint8)
    recall=float(np.sum(prototype&cv2.dilate(candidate,kernel))/max(1,int(prototype.sum())))
    precision=float(np.sum(candidate&cv2.dilate(prototype,kernel))/max(1,int(candidate.sum())))
    return min(recall,precision)


@dataclass(frozen=True)
class CaptionEvidence:
    passed: bool
    score: float
    yellow_pixels: int
    caption_bbox: tuple
    click_bbox: tuple
    click_point: tuple
    config_sha256: str


class CancelCaptionDetector:
    def __init__(self,path):
        self.path=Path(path).resolve();raw=self.path.read_bytes();self.sha256=hashlib.sha256(raw).hexdigest()
        config=json.loads(raw)
        if config.get("schema")!="response-cancel-caption-v1" or config.get("parameters")!=PARAMETERS:
            raise ValueError("Cancel captionの固定方式・尺度が一致しません")
        refs=config.get("references",[])
        if len(refs)!=20:raise ValueError("事故前固定派生End crop20枚が必要です")
        self.files={str(self.path):self.sha256};self.stats={};features=[]
        for ref in refs:
            asset=(self.path.parent/ref["image"]).resolve()
            if not asset.is_relative_to(self.path.parent):raise ValueError("派生assetが校正外です")
            data=asset.read_bytes()
            if hashlib.sha256(data).hexdigest()!=ref["sha256"]:raise ValueError("Cancel派生asset hash不一致")
            pixels=read_image(asset)
            if pixels.shape!=(40,178,3):raise ValueError("派生Cancel cropは178x40のみです")
            features.append(yellow_shape(pixels[13:27,50:128]))
            self.files[str(asset)]=ref["sha256"]
        self.prototype=(np.mean(np.stack(features),axis=0)>=.5).astype(np.uint8)
        if int(self.prototype.sum())!=219 or hashlib.sha256(self.prototype.tobytes()).hexdigest()!=config["prototype_sha256"]:
            raise ValueError("文字prototypeの画素数/hashが固定値と一致しません")
        self.files[str(Path(__file__).resolve())]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        for name in self.files:
            stat=Path(name).stat();self.stats[name]=(stat.st_size,stat.st_mtime_ns)

    def assert_unchanged(self):
        for name,expected in self.stats.items():
            stat=Path(name).stat()
            if (stat.st_size,stat.st_mtime_ns)!=expected:raise ValueError("Cancel caption asset変更を検出")

    def detect(self,pixels):
        self.assert_unchanged()
        if pixels.dtype!=np.uint8 or pixels.shape!=(720,1280,3):raise ValueError("native client1280x720が必要です")
        x,y,w,h=PARAMETERS["caption_bbox"];candidate=yellow_shape(pixels[y:y+h,x:x+w])
        score=tolerant_shape_score(self.prototype,candidate)
        return CaptionEvidence(score>=.85,score,int(candidate.sum()),tuple(PARAMETERS["caption_bbox"]),
            tuple(PARAMETERS["click_bbox"]),tuple(PARAMETERS["click_point"]),self.sha256)

    def provenance(self):
        return {"schema":"response-cancel-caption-v1","config_sha256":self.sha256,"parameters":PARAMETERS,
            "prototype_pixels":int(self.prototype.sum()),"prototype_sha256":hashlib.sha256(self.prototype.tobytes()).hexdigest(),
            "binary_confidence":"predicate pass only, not probability", "enabled_proxy":"bright yellow glyph; disabled actual samples unavailable",
            "files":dict(self.files)}
