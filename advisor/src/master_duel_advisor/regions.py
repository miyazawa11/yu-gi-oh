from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from pydantic import Field, StrictInt, model_validator

from .models import Model


class Rect(Model):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def within_frame(self):
        if self.x + self.width > 1.0000001 or self.y + self.height > 1.0000001:
            raise ValueError("矩形が表示範囲を超えています")
        return self

    def crop(self, pixels: np.ndarray) -> np.ndarray:
        h, w = pixels.shape[:2]
        x1, y1 = math.floor(self.x*w), math.floor(self.y*h)
        x2, y2 = min(w, math.ceil((self.x+self.width)*w)), min(h, math.ceil((self.y+self.height)*h))
        result = pixels[y1:y2, x1:x2]
        if result.size == 0:
            raise ValueError("切り抜き領域が空です")
        return result


class Exemplar(Model):
    label: str
    image: str


class Region(Model):
    rect: Rect
    kind: str = Field(pattern="^(number|template|card|action|unobserved)$")
    exemplars: list[Exemplar] = Field(default_factory=list)
    threshold: float = Field(default=0.95, ge=0.5, le=1)
    margin: float = Field(default=0.03, gt=0, le=1)
    feature: str = Field(default="rgb", pattern="^(rgb|stable_rgb)$")
    stable_rgb_excluded_rows: list[StrictInt] = Field(default_factory=list, exclude_if=lambda value: not value)
    # カード/対象を固定した専用 UI のみで使用します。
    card_id: str | None = None
    target: str | None = None

    @model_validator(mode="after")
    def fixed_field_mask(self):
        if self.stable_rgb_excluded_rows and (self.feature != "stable_rgb"
                or self.stable_rgb_excluded_rows != list(range(6,25))):
            raise ValueError("field除外maskはstable_rgb descriptor rows6..24の固定条件のみです")
        return self


class CompositeEvidence(Model):
    """複数の実テンプレート陽性をANDで照合する限定文脈。"""
    id: str
    when: dict[str, str] = Field(min_length=2)
    emit: dict[str, str] = Field(min_length=1)


class RecognitionResource(Model):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Calibration(Model):
    name: str
    viewport: Rect = Field(default_factory=lambda: Rect(x=0, y=0, width=1, height=1))
    aspect_ratio: float = Field(default=16/9, gt=0)
    aspect_tolerance: float = Field(default=0.02, ge=0, le=0.2)
    regions: dict[str, Region]
    composites: list[CompositeEvidence] = Field(default_factory=list)
    recognition_assets: dict[str, RecognitionResource] = Field(default_factory=dict, exclude_if=lambda value: not value)

    @model_validator(mode="after")
    def positive_composites(self):
        masked = {name for name, region in self.regions.items() if region.stable_rgb_excluded_rows}
        if masked and (masked != {"fact.zone.self.monster_2.occupancy", "action.inspect_zone"}
                or set(self.recognition_assets) != {"detail_name_registry", "action_evidence_detector"}):
            raise ValueError("field除外maskは専用inspectのzone/inspect一対と固定componentが必要です")
        if set(self.recognition_assets) - {"detail_name_registry", "action_evidence_detector"}:
            raise ValueError("未対応の認識componentが指定されています")
        if len({c.id for c in self.composites}) != len(self.composites):
            raise ValueError("複合証拠IDが重複しています")
        allowed = {"ui.prompt", "ui.animation", "game.terminal", "phase", "turn_player"}
        for context in self.composites:
            if set(context.emit) - allowed:
                raise ValueError("複合証拠の出力項目が不正です")
            for name, label in context.when.items():
                region = self.regions.get(name)
                if (not name.startswith("fact.") or region is None or region.kind != "template"
                        or region.threshold < .98 or label not in {e.label for e in region.exemplars}):
                    raise ValueError("複合証拠は閾値.98以上の実factテンプレートを必要とします")
            for name, value in context.emit.items():
                values = {"ui.animation": {"idle", "playing"}, "game.terminal": {"active", "ended"},
                          "phase": {"DRAW", "STANDBY", "MAIN1", "BATTLE", "MAIN2", "END"},
                          "turn_player": {"self", "opponent"}}.get(name)
                if not value or (values is not None and value not in values):
                    raise ValueError("複合証拠の出力値が不正です")
        return self

    def crop_regions(self, pixels: np.ndarray) -> dict[str, np.ndarray]:
        view = self.viewport.crop(pixels)
        ratio = view.shape[1] / view.shape[0]
        if abs(ratio/self.aspect_ratio-1) > self.aspect_tolerance:
            raise ValueError("表示範囲の縦横比が校正と異なります。黒帯や切り抜き範囲を設定してください")
        return {name: region.rect.crop(view) for name, region in self.regions.items()}


def load_calibration(path: Path) -> Calibration:
    return Calibration.model_validate(json.loads(path.read_text(encoding="utf-8")))
