"""選択詳細の名前画像だけを識別します。所属ゾーンや操作には結び付けません。"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .capture import Frame
from .image_io import read_image
from .perception import fingerprint

ROI = (24, 106, 217, 24)
SHAPE = (720, 1280, 3)
MIN_SCORE = .98
MIN_MARGIN = .03


@dataclass(frozen=True)
class DetailNameEvidence:
    cid: str | None
    namespace: str
    score: float
    top_candidate: str | None
    top2_cid: str | None
    top2_score: float
    margin: float
    frame_seq: int
    observed_at: float
    roi: tuple[int, int, int, int]
    registry_sha256: str
    reference_sha256: str | None
    unknown_reason: str | None
    scope: str = "selected_detail_only"


class DetailNameRegistry:
    """フレーム間でCIDを保持しない小さな固定レジストリです。"""

    def __init__(self, path: Path):
        raw = path.read_bytes()
        self.sha256 = hashlib.sha256(raw).hexdigest()
        data = json.loads(raw)
        if (data.get("schema") != "detail-name-registry-v1"
                or data.get("namespace") != "konami"
                or data.get("source") != "master_duel_selected_detail_name"
                or data.get("roi") != list(ROI) or data.get("capture_shape") != list(SHAPE)
                or data.get("feature") != "bgr_area_64x32_mae"
                or data.get("minimum_score") != MIN_SCORE or data.get("minimum_margin") != MIN_MARGIN):
            raise ValueError("詳細名レジストリの固定条件が一致しません")
        self.references = []
        base = path.parent.resolve()
        for item in data["references"]:
            image_path = (base / item["image"]).resolve()
            if not image_path.is_relative_to(base):
                raise ValueError("参照画像がレジストリ外にあります")
            if hashlib.sha256(image_path.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("参照画像のハッシュが一致しません")
            image = read_image(str(image_path))
            if image is None or image.shape != (ROI[3], ROI[2], 3):
                raise ValueError("名前参照画像のサイズが不正です")
            if not item.get("source_sha256") or not item.get("source_image"):
                raise ValueError("参照元の証拠がありません")
            self.references.append((str(item["cid"]), fingerprint(image), item["sha256"]))
        if {cid for cid, _, _ in self.references} != {"9455", "13581", "12950"} or len(self.references) != 3:
            raise ValueError("登録CIDは固定3種類でなければなりません")

    def recognize(self, frame: Frame) -> DetailNameEvidence:
        ranked = []
        reason = None
        if frame.pixels.shape != SHAPE or frame.pixels.dtype != np.uint8:
            reason = "invalid_capture_shape_or_dtype"
        elif not math.isfinite(frame.captured_at) or frame.sequence < 0:
            reason = "invalid_frame_metadata"
        else:
            x, y, w, h = ROI
            feature = fingerprint(frame.pixels[y:y+h, x:x+w])
            ranked = sorted(((float(1-np.mean(np.abs(feature-ref))), cid, digest)
                             for cid, ref, digest in self.references), reverse=True)
        top = ranked[0] if ranked else (0., None, None)
        second = ranked[1] if ranked else (0., None, None)
        margin = top[0] - second[0]
        if reason is None:
            reason = "below_score_threshold" if top[0] < MIN_SCORE else "ambiguous_margin" if margin < MIN_MARGIN else None
        return DetailNameEvidence(top[1] if reason is None else None, "konami", top[0], top[1],
                                  second[1], second[0], margin, frame.sequence, frame.captured_at,
                                  ROI, self.sha256, top[2], reason)
