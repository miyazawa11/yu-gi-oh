"""固定召喚UIの局所探索。候補位置の証拠だけを返し、入力へ接続しません。"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import Field

from .capture import Frame
from .models import Model
from .perception import TemplateMatcher, fingerprint
from .regions import load_calibration

SHAPE = (720, 1280, 3)
SEARCH = {"radius_x": 64, "radius_y": 24, "coarse_step": 4, "refine_radius": 3,
          "suppression": "half_template_width_or_height"}
PROFILES = {"maxxc-menu-v1": (434, 496, 73, 98), "solar-menu-v2": (380, 497, 74, 79)}
UNVERIFIED = ("SPECIAL_SUMMON", "FLIP_SUMMON", "DISABLED_NORMAL_SUMMON")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CaptureContext(Model):
    mode: Literal["offline_saved_image", "live_capture"]
    capture_source: str = Field(min_length=1)
    client_rect: tuple[int, int, int, int] | None = None
    captured_at_clock: Literal["monotonic", "unspecified_zero_not_capture_time"]
    frame_seq_semantics: Literal["capture_sequence", "manifest_index_not_capture_sequence"]


class ButtonEvidence(Model):
    candidate_type: Literal["NORMAL_SUMMON"] | None
    profile_id: str
    evidence_bbox: tuple[int, int, int, int] | None
    bbox_semantics: Literal["template_evidence_crop_not_button_boundary"] = "template_evidence_crop_not_button_boundary"
    search_bbox: tuple[int, int, int, int]
    score: float = Field(ge=0, le=1)
    position_runner_up_score: float = Field(ge=0, le=1)
    position_runner_up_bbox: tuple[int, int, int, int] | None
    position_margin: float = Field(ge=0, le=1)
    type_runner_up: None = None
    type_margin: None = None
    unverified_alternatives: tuple[str, ...] = UNVERIFIED
    frame_seq: int
    observed_at: float
    capture_context: CaptureContext
    detector_sha256: str
    profile_sha256: str
    unknown_reason: str | None
    scope: Literal["readonly_ui_location_candidate"] = "readonly_ui_location_candidate"
    usable_for_input: Literal[False] = False


class ActionEvidenceDetector:
    """旧profileを有限探索する未検証部品。カードID・ゾーン・クリック点は返しません。"""

    def __init__(self, config_path: Path):
        self.config_path = config_path.resolve()
        self.sha256 = digest(self.config_path)
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        if (data.get("schema") != "readonly-action-evidence-v1"
                or data.get("capture_shape") != list(SHAPE) or data.get("search") != SEARCH
                or data.get("minimum_score") != .98 or data.get("minimum_position_margin") != .03
                or data.get("action_kind") != "NORMAL_SUMMON" or data.get("usable_for_input") is not False
                or data.get("unverified_alternatives") != list(UNVERIFIED)):
            raise ValueError("局所探索の固定条件が一致しません")
        if set(data.get("profiles", {})) != set(PROFILES):
            raise ValueError("局所探索は固定G/Solar profileだけを使用します")
        self.profiles = {}
        self._files = {self.config_path: self.sha256}
        for name, item in data["profiles"].items():
            path = (self.config_path.parent / item["calibration"]).resolve()
            if digest(path) != item["calibration_sha256"]:
                raise ValueError("校正ファイルのハッシュが一致しません")
            layout = load_calibration(path)
            region = layout.regions["action.normal_summon"]
            if (region.kind != "action" or region.feature != "stable_rgb" or region.threshold != .98
                    or region.margin != .03 or item["evidence_roi"] != list(PROFILES[name])
                    or {e.label for e in region.exemplars} != {"NORMAL_SUMMON"}
                    or region.rect.crop(np.zeros(SHAPE, np.uint8)).shape[:2]
                    != (PROFILES[name][3], PROFILES[name][2])):
                raise ValueError("召喚UI profileの固定条件が一致しません")
            # ピクセル位置も検査し、同サイズの別領域へ宣言だけを変えません。
            x, y, w, h = PROFILES[name]
            if (math.floor(region.rect.x * SHAPE[1]), math.floor(region.rect.y * SHAPE[0])) != (x, y):
                raise ValueError("召喚UI profileの座標が一致しません")
            matcher = TemplateMatcher(region, path.parent)
            if matcher.asset_hashes != item["template_assets"] or matcher.stable_statistics != item["stable_features"]:
                raise ValueError("参照画像または安定特徴のハッシュが一致しません")
            if len(matcher.stable_profiles) != 1:
                raise ValueError("操作種別の参照が一意ではありません")
            _, prototype, mask = matcher.stable_profiles[0]
            prototype.setflags(write=False)
            mask.setflags(write=False)
            profile_sha = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
            self.profiles[name] = (prototype, mask, profile_sha)
            self._files[path] = item["calibration_sha256"]
            for relative, sha in matcher.asset_hashes.items():
                self._files[(path.parent / relative).resolve()] = sha
        self._stats = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in self._files}

    def assert_assets_unchanged(self, *, full_hash: bool = False):
        """通常変更はstat、評価の前後は全内容hashで拒否します。"""
        for path, expected in self._files.items():
            stat = path.stat()
            if ((stat.st_size, stat.st_mtime_ns) != self._stats[path]
                    or (full_hash and digest(path) != expected)):
                raise ValueError("固定後のdetector/校正/参照画像変更を検出しました")

    def provenance(self) -> dict:
        return {"detector_sha256": self.sha256, "files": {str(p): sha for p, sha in self._files.items()},
                "profile_sha256": {name: values[2] for name, values in self.profiles.items()},
                "component_source_sha256": {name: digest(Path(__file__).with_name(name + ".py"))
                                            for name in ("action_evidence", "perception", "regions", "capture", "models", "image_io")},
                "usable_for_input": False, "unverified_alternatives": list(UNVERIFIED)}

    @staticmethod
    def _valid_pixels(pixels):
        return isinstance(pixels, np.ndarray) and pixels.shape == SHAPE and pixels.dtype == np.uint8

    @staticmethod
    def _frame_reason(frame: Frame, context: CaptureContext):
        if not ActionEvidenceDetector._valid_pixels(frame.pixels):
            return "invalid_capture_shape_or_dtype"
        if (isinstance(frame.sequence, bool) or not isinstance(frame.sequence, int) or frame.sequence < 0
                or not isinstance(frame.captured_at, (int, float)) or not math.isfinite(frame.captured_at)
                or frame.captured_at < 0):
            return "invalid_frame_metadata"
        if context.mode == "offline_saved_image":
            if (frame.captured_at != 0 or context.captured_at_clock != "unspecified_zero_not_capture_time"
                    or context.frame_seq_semantics != "manifest_index_not_capture_sequence"):
                return "offline_frame_cannot_be_freshened"
        elif (frame.captured_at <= 0 or context.captured_at_clock != "monotonic"
              or context.frame_seq_semantics != "capture_sequence" or context.client_rect is None):
            return "invalid_live_capture_provenance"
        if context.client_rect is not None:
            l, t, r, b = context.client_rect
            if (r - l, b - t) != (SHAPE[1], SHAPE[0]):
                return "client_rect_shape_mismatch"
        return None

    def score_crop(self, pixels: np.ndarray, profile_id: str, bbox: tuple[int, int, int, int]) -> float:
        """診断用の類似度だけ。Action種別・入力可否・新鮮さを証明しません。"""
        if not self._valid_pixels(pixels):
            raise ValueError("BGR uint8 client 1280x720画像が必要です")
        if profile_id not in self.profiles:
            raise ValueError("未登録の局所探索profileです")
        if (len(bbox) != 4 or any(isinstance(v, bool) or not isinstance(v, int) for v in bbox)
                or bbox[2:] != PROFILES[profile_id][2:]):
            raise ValueError("診断cropのサイズがprofileと一致しません")
        x, y, w, h = bbox
        if x < 0 or y < 0 or x + w > SHAPE[1] or y + h > SHAPE[0]:
            raise ValueError("診断cropがclient範囲外です")
        prototype, mask, _ = self.profiles[profile_id]
        feature = fingerprint(pixels[y:y+h, x:x+w])
        return float(1 - np.mean(np.abs(feature - prototype)[mask]))

    def recognize(self, frame: Frame, context: CaptureContext, profile_id: str) -> ButtonEvidence:
        if profile_id not in self.profiles:
            raise ValueError("未登録の局所探索profileです")
        self.assert_assets_unchanged()
        x, y, w, h = PROFILES[profile_id]
        search_bbox = (x - 64, y - 24, w + 128, h + 48)
        reason = self._frame_reason(frame, context)
        scores = []
        if reason is None:
            for dy in range(-24, 25, 4):
                for dx in range(-64, 65, 4):
                    box = (x + dx, y + dy, w, h)
                    scores.append((self.score_crop(frame.pixels, profile_id, box), box))
            coarse = max(scores)
            # 粗探索範囲を超える精探索は行いません。
            for dy in range(-3, 4):
                for dx in range(-3, 4):
                    xx, yy = coarse[1][0] + dx, coarse[1][1] + dy
                    if x - 64 <= xx <= x + 64 and y - 24 <= yy <= y + 24:
                        box = (xx, yy, w, h)
                        scores.append((self.score_crop(frame.pixels, profile_id, box), box))
        best = max(scores, default=(0., None))
        second = max((v for v in scores if best[1] is not None
                      and (abs(v[1][0] - best[1][0]) >= w / 2 or abs(v[1][1] - best[1][1]) >= h / 2)),
                     default=(0., None))
        margin = best[0] - second[0]
        if reason is None:
            reason = "below_score_threshold" if best[0] < .98 else "ambiguous_position_margin" if margin < .03 else None
        # 不正metadataもJSONへ安全に保存するため、非有限値は未知値0にします。
        seq = frame.sequence if isinstance(frame.sequence, int) and not isinstance(frame.sequence, bool) else -1
        observed = frame.captured_at if isinstance(frame.captured_at, (int, float)) and math.isfinite(frame.captured_at) else 0.
        return ButtonEvidence(candidate_type="NORMAL_SUMMON" if reason is None else None,
                              profile_id=profile_id, evidence_bbox=best[1], search_bbox=search_bbox,
                              score=best[0], position_runner_up_score=second[0], position_runner_up_bbox=second[1],
                              position_margin=margin, frame_seq=seq, observed_at=observed, capture_context=context,
                              detector_sha256=self.sha256, profile_sha256=self.profiles[profile_id][2], unknown_reason=reason)
