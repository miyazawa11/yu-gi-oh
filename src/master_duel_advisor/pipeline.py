from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np

from .capture import Frame
from .decision import DecisionContext, DecisionEngine
from .models import GameState
from .perception import Perception
from .rules import ActionGenerator
from .regions import Calibration
from .tracking import Tracker


class FrameGate:
    def __init__(self, threshold: float = 0.005, refresh_seconds: float = 1.0, calibration: Calibration | None = None):
        self.threshold, self.refresh_seconds = threshold, refresh_seconds
        self.calibration = calibration
        self.previous: list[np.ndarray] | None = None
        self.last_time: float | None = None

    def accept(self, frame: Frame) -> bool:
        crops = [frame.pixels]
        if self.calibration:
            try:
                crops.extend(self.calibration.crop_regions(frame.pixels).values())
            except ValueError:
                self.previous = None
                return True  # 配置が不正な場合は認識処理で古い既知状態を消去します。
        thumbnails = [cv2.resize(crop, (160, 90)).astype(np.float32)/255 for crop in crops]
        changed = self.previous is None or any(float(np.mean(np.abs(current-previous))) >= self.threshold for current,previous in zip(thumbnails,self.previous))
        expired = self.last_time is None or frame.captured_at-self.last_time >= self.refresh_seconds
        if changed or expired:
            self.previous, self.last_time = thumbnails, frame.captured_at
            return True
        return False


class Pipeline:
    def __init__(self, perception: Perception, rules: ActionGenerator | None = None):
        self.perception = perception
        self.rules = rules or ActionGenerator()
        self.tracker, self.engine = Tracker(), DecisionEngine()
        self.last: dict | None = None

    def process(self, frame: Frame, capture_read_ms: float = 0) -> dict:
        start = time.perf_counter()
        error = None
        try:
            state = self.perception.process(frame)
        except ValueError as exc:
            # 不正な表示範囲・配置では未知として扱い、前回の根拠を流用しません。
            state = GameState(sequence=frame.sequence, captured_at=frame.captured_at, media_time=frame.media_time)
            error = str(exc)
        perception_ms = (time.perf_counter()-start)*1000
        self.tracker.update(state)
        decision_start = time.perf_counter()
        actions = self.rules.generate(state, time.monotonic())
        ids = {obs.value.card_id for player in [state.self, state.opponent] for obs in player.zones.values() if obs.value is not None}
        cards = tuple(card for card_id in sorted(ids) if (card := self.perception.cards.get(card_id)) is not None)
        recommendation = self.engine.decide(DecisionContext(state, tuple(self.tracker.events), cards, tuple(actions)))
        decision_ms = (time.perf_counter()-decision_start)*1000
        self.last = {"state": state.model_dump(mode="json"), "events": [event.model_dump(mode="json") for event in self.tracker.events], "legal_actions": [a.model_dump(mode="json") for a in actions], "recommendation": recommendation.model_dump(mode="json"), "error": error, "metrics": {"capture_read_ms": capture_read_ms, "perception_ms": perception_ms, "decision_ms": decision_ms, "total_compute_ms": capture_read_ms+(time.perf_counter()-start)*1000, "api_calls": 0, "api_cost_usd": 0}}
        return self.last


def save_json(path: Path, value: object):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")
    temporary.replace(path)
