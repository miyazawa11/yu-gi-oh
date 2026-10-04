from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from pydantic import Field, model_validator

from .models import Model


class Rect(Model):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def within_frame(self):
        if self.x + self.width > 1.0000001 or self.y + self.height > 1.0000001:
            raise ValueError("Rectangle extends beyond viewport")
        return self

    def crop(self, pixels: np.ndarray) -> np.ndarray:
        h, w = pixels.shape[:2]
        x1, y1 = math.floor(self.x*w), math.floor(self.y*h)
        x2, y2 = min(w, math.ceil((self.x+self.width)*w)), min(h, math.ceil((self.y+self.height)*h))
        result = pixels[y1:y2, x1:x2]
        if result.size == 0:
            raise ValueError("Empty crop")
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


class Calibration(Model):
    name: str
    viewport: Rect = Field(default_factory=lambda: Rect(x=0, y=0, width=1, height=1))
    aspect_ratio: float = Field(default=16/9, gt=0)
    aspect_tolerance: float = Field(default=0.02, ge=0, le=0.2)
    regions: dict[str, Region]

    def crop_regions(self, pixels: np.ndarray) -> dict[str, np.ndarray]:
        view = self.viewport.crop(pixels)
        ratio = view.shape[1] / view.shape[0]
        if abs(ratio/self.aspect_ratio-1) > self.aspect_tolerance:
            raise ValueError("Viewport aspect ratio differs from calibration; configure letterboxing/crop")
        return {name: region.rect.crop(view) for name, region in self.regions.items()}


def load_calibration(path: Path) -> Calibration:
    return Calibration.model_validate(json.loads(path.read_text(encoding="utf-8")))
