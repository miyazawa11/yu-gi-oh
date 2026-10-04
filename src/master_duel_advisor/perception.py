from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .capture import Frame
from .cards import CardDatabase
from .models import Action, ActionType, CardIdentity, GameState, Observation, Phase, Player, PlayerState
from .regions import Calibration, Region


class NumericOCR(Protocol):
    def read(self, crop: np.ndarray, maximum: int) -> tuple[int | None, float]: ...


class TesseractOCR:
    def __init__(self, command: str = "tesseract"):
        self.command = shutil.which(command)

    def read(self, crop: np.ndarray, maximum: int) -> tuple[int | None, float]:
        if self.command is None:
            return None, 0
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        # Upscaling large anti-aliased digits caused 5200→9200 regressions.
        # Only enlarge genuinely small crops, then require two renderings agree.
        if gray.shape[0] < 40:
            scale = 40/gray.shape[0]
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        # A white page improves sparse numeric OCR. Preserve the shape of digits.
        if np.mean(binary) < 127:
            binary = 255 - binary
            gray = 255 - gray
        predictions = []
        for rendering in [gray, binary]:
            rendering = cv2.copyMakeBorder(rendering, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
            predictions.append(self._read_rendering(rendering, maximum))
        if predictions[0][0] is None or predictions[0][0] != predictions[1][0]:
            return None, 0
        return predictions[0][0], min(predictions[0][1], predictions[1][1])

    def _read_rendering(self, rendering: np.ndarray, maximum: int) -> tuple[int | None, float]:
        ok, png = cv2.imencode(".png", rendering)
        if not ok:
            return None, 0
        try:
            result = subprocess.run([self.command, "stdin", "stdout", "--psm", "7", "-c", "tessedit_char_whitelist=0123456789", "tsv"], input=png.tobytes(), capture_output=True, timeout=3, check=True)
        except (subprocess.SubprocessError, OSError):
            return None, 0
        tokens, confidences = [], []
        for line in result.stdout.decode("utf-8", errors="replace").splitlines()[1:]:
            fields = line.split("\t")
            if len(fields) == 12 and fields[0] == "5" and fields[11].strip():
                tokens.append(fields[11].strip())
                try:
                    confidences.append(max(0, min(1, float(fields[10])/100)))
                except ValueError:
                    return None, 0
        if len(tokens) != 1 or not re.fullmatch(r"\d{1,6}", tokens[0]):
            return None, 0
        value = int(tokens[0])
        confidence = min(confidences, default=0)
        if value > maximum or confidence < 0.9:
            return None, 0
        return value, confidence


def fingerprint(pixels: np.ndarray) -> np.ndarray:
    """Color-preserving normalized image descriptor, not a trained embedding."""
    return cv2.resize(pixels, (64, 32), interpolation=cv2.INTER_AREA).astype(np.float32)/255


class TemplateMatcher:
    def __init__(self, region: Region, base: Path):
        self.region = region
        self.templates: list[tuple[str, np.ndarray]] = []
        for exemplar in region.exemplars:
            path = (base/exemplar.image).resolve()
            # Calibration uses local assets; forbid escaping its own directory.
            if not path.is_relative_to(base.resolve()):
                raise ValueError("Template assets must be within calibration directory")
            image = cv2.imread(str(path))
            if image is None:
                raise ValueError(f"Cannot read exemplar: {path}")
            self.templates.append((exemplar.label, fingerprint(image)))
        if region.kind in {"template", "card", "action"} and not self.templates:
            raise ValueError("Template regions require exemplars")

    def match(self, crop: np.ndarray) -> tuple[str | None, float]:
        descriptor = fingerprint(crop)
        scores: dict[str, float] = {}
        for label, template in self.templates:
            score = float(1 - np.mean(np.abs(descriptor-template)))
            scores[label] = max(scores.get(label, 0), score)
        ranked = sorted(scores.items(), key=lambda entry: entry[1], reverse=True)
        if not ranked:
            return None, 0
        label, best = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        if best < self.region.threshold or best-runner_up < self.region.margin:
            return None, 0
        return label, best


class Perception:
    def __init__(self, calibration: Calibration, base: Path, cards: CardDatabase, ocr: NumericOCR | None = None):
        self.calibration, self.cards = calibration, cards
        self.ocr = ocr or TesseractOCR()
        self.matchers = {name: TemplateMatcher(region, base) for name, region in calibration.regions.items() if region.kind in {"template", "card", "action"}}
        self._validate_semantics()

    def _validate_semantics(self):
        numeric_names = {"self.lp", "opponent.lp", "self.hand_count", "opponent.hand_count", "turn"}
        for name, region in self.calibration.regions.items():
            labels = [e.label for e in region.exemplars]
            if region.kind == "unobserved":
                continue
            if name in numeric_names:
                if region.kind not in {"number", "template"}:
                    raise ValueError(f"Numeric field has incompatible kind: {name}")
                maximum = 999999 if name.endswith(".lp") else 999 if name == "turn" else 60
                if any(not label.isdecimal() or int(label) > maximum for label in labels):
                    raise ValueError(f"Invalid numeric template label: {name}")
            elif name == "phase":
                if region.kind != "template":
                    raise ValueError("phase requires templates")
                for label in labels:
                    Phase(label)
            elif name == "turn_player":
                if region.kind != "template":
                    raise ValueError("turn_player requires templates")
                for label in labels:
                    Player(label)
            elif name.startswith("action."):
                if region.kind != "action":
                    raise ValueError("Action fields require action templates")
                for label in labels:
                    ActionType(label)
            elif re.fullmatch(r"(self|opponent)\.zones\.[a-zA-Z0-9_]+", name):
                if region.kind != "card":
                    raise ValueError("Zone identities require card templates")
            else:
                raise ValueError(f"Unsupported semantic region: {name}")

    def process(self, frame: Frame) -> GameState:
        crops = self.calibration.crop_regions(frame.pixels)
        observed: dict[str, Observation] = {}
        actions: list[Action] = []
        for name, region in self.calibration.regions.items():
            value, confidence = None, 0.0
            if region.kind == "number":
                maximum = 999999 if name.endswith(".lp") else 999 if name == "turn" else 60
                value, confidence = self.ocr.read(crops[name], maximum)
            elif name in self.matchers:
                value, confidence = self.matchers[name].match(crops[name])
            if region.kind == "action":
                if value is not None:
                    actions.append(Action(type=ActionType(value), confidence=confidence, source_region=name, observed_at=frame.captured_at))
                continue
            if name.startswith(("self.zones.", "opponent.zones.")) and value is not None:
                card = self.cards.get(str(value))
                if card is None:
                    value, confidence = None, 0
                else:
                    value = CardIdentity(card_id=card.card_id, name=card.name)
            elif name == "phase" and value is not None:
                value = Phase(value)
            elif name == "turn_player" and value is not None:
                value = Player(value)
            elif value is not None:
                value = int(value)
            observed[name] = Observation(value=value, confidence=confidence, source=f"{region.kind}:{name}", observed_at=frame.captured_at)

        def obs(name):
            return observed.get(name, Observation(observed_at=frame.captured_at))

        def player(side):
            prefix = side+".zones."
            return PlayerState(lp=obs(side+".lp"), hand_count=obs(side+".hand_count"), zones={key[len(prefix):]: value for key, value in observed.items() if key.startswith(prefix)})

        return GameState(sequence=frame.sequence, captured_at=frame.captured_at, media_time=frame.media_time, turn=obs("turn"), turn_player=obs("turn_player"), phase=obs("phase"), self=player("self"), opponent=player("opponent"), visible_actions=actions)
