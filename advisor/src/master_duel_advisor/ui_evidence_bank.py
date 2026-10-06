"""既存の同義UI参照を束ねる限定inspect経路。座標証拠と手札輪郭だけを返します。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from .action_evidence import ActionEvidenceDetector, ButtonEvidence, PROFILES, SEARCH, UNVERIFIED, digest
from .perception import TemplateMatcher, fingerprint
from .regions import load_calibration


class UiEvidenceBank:
    """同位置のNORMAL参照は同義として統合し、別位置の競合を保持します。"""

    def __init__(self, config_path: Path):
        self.config_path = config_path.resolve()
        self.sha256 = digest(self.config_path)
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        if (data.get("schema") != "normal-inspect-ui-bank-v1" or data.get("search") != SEARCH
                or data.get("profile_id") != "solar-menu-v2" or data.get("minimum_score") != .98
                or data.get("minimum_position_margin") != .03 or data.get("hand_offset") != [27, 82]
                or data.get("hand_radius") != 3 or data.get("hand_size") != [18, 112]
                or data.get("usable_for_input") is not False
                or len(data.get("detectors", [])) != 2 or len(data.get("hand_calibrations", [])) != 2):
            raise ValueError("限定UI bankの固定探索・閾値・参照数が一致しません")
        self._files = {self.config_path: self.sha256}
        self.detectors = []
        self.hand_matchers = []
        for entry in data["detectors"]:
            path = (self.config_path.parent / entry["path"]).resolve()
            if digest(path) != entry["sha256"]:
                raise ValueError("既存detector宣言hash不一致")
            detector = ActionEvidenceDetector(path)
            self.detectors.append(detector)
            self._files.update({Path(p): sha for p, sha in detector.provenance()["files"].items()})
        for entry in data["hand_calibrations"]:
            path = (self.config_path.parent / entry["path"]).resolve()
            if digest(path) != entry["sha256"]:
                raise ValueError("既存手札輪郭校正hash不一致")
            region = load_calibration(path).regions["fact.inspect_context.hand_selected"]
            if (region.feature != "stable_rgb" or region.threshold != .98 or region.margin != .03
                    or {e.label for e in region.exemplars} != {"true"}):
                raise ValueError("手札輪郭は既存の同義陽性参照だけを使用します")
            matcher = TemplateMatcher(region, path.parent)
            self.hand_matchers.append(matcher)
            self._files[path] = entry["sha256"]
            self._files.update({(path.parent / p).resolve(): sha for p, sha in matcher.asset_hashes.items()})
        self._prototypes = [d.profiles["solar-menu-v2"][:2] for d in self.detectors]
        self.hand_feature = data.get("hand_feature", "stable_rgb")
        self.hand_geometry_sha256 = None
        self.last_hand_diagnostic = None
        if self.hand_feature == "raised_card_lines_v1":
            from .hand_geometry import PARAMETERS, PARAMETERS_SHA256
            if data.get("hand_geometry") != PARAMETERS:
                raise ValueError("手札幾何の固定パラメータが一致しません")
            self.hand_geometry_sha256 = PARAMETERS_SHA256
        elif self.hand_feature != "stable_rgb":
            raise ValueError("未知の手札証拠方式です")
        profile_sha = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        # 既存座標・goal guardはslot2の固定profile hashを照合します。
        self.profiles = {"solar-menu-v2": (*self._prototypes[0], profile_sha)}
        self._stats = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in self._files}

    def assert_assets_unchanged(self, *, full_hash=False):
        for path, expected in self._files.items():
            stat = path.stat()
            if ((stat.st_size, stat.st_mtime_ns) != self._stats[path]
                    or (full_hash and digest(path) != expected)):
                raise ValueError("固定UI bank参照変更を検出しました")

    def provenance(self):
        result = {"detector_sha256": self.sha256, "schema": "normal-inspect-ui-bank-v1",
                "files": {str(p): sha for p, sha in self._files.items()},
                "profile_sha256": {"solar-menu-v2": self.profiles["solar-menu-v2"][2]},
                "same_position_aggregation": "maximum_same_normal_class",
                "hand_offset": [27, 82], "hand_radius": 3,
                "hand_features": [m.stable_statistics for m in self.hand_matchers],
                "usable_for_input": False, "unverified_alternatives": list(UNVERIFIED)}
        if self.hand_feature != "stable_rgb":
            result.update(hand_feature=self.hand_feature, hand_geometry_sha256=self.hand_geometry_sha256)
        return result

    def _scores(self, pixels, box):
        x, y, w, h = box
        feature = fingerprint(pixels[y:y+h, x:x+w])
        return [float(1-np.mean(np.abs(feature-prototype)[mask])) for prototype, mask in self._prototypes]

    def recognize(self, frame, context, profile_id):
        if profile_id != "solar-menu-v2":
            raise ValueError("UI bankは限定NORMAL profile専用です")
        self.assert_assets_unchanged()
        reason = ActionEvidenceDetector._frame_reason(frame, context)
        x, y, w, h = PROFILES[profile_id]
        scores = {}
        coarse = []
        if reason is None:
            for dy in range(-24, 25, 4):
                for dx in range(-64, 65, 4):
                    box = (x+dx, y+dy, w, h)
                    values = self._scores(frame.pixels, box)
                    scores[box] = max(values)
                    coarse.append((values, box))
            # 各表示参照の局所最大を精探索。同位置は参照重複でrunnerにしません。
            for index in range(len(self._prototypes)):
                anchor = max(coarse, key=lambda item: item[0][index])[1]
                for dy in range(-3, 4):
                    for dx in range(-3, 4):
                        xx, yy = anchor[0]+dx, anchor[1]+dy
                        box = (xx, yy, w, h)
                        if x-64 <= xx <= x+64 and y-24 <= yy <= y+24 and box not in scores:
                            scores[box] = max(self._scores(frame.pixels, box))
        best = max(((score, box) for box, score in scores.items()), default=(0., None))
        second = max(((score, box) for box, score in scores.items() if best[1] is not None
                      and (abs(box[0]-best[1][0]) >= w/2 or abs(box[1]-best[1][1]) >= h/2)),
                     default=(0., None))
        margin = best[0]-second[0]
        if reason is None:
            reason = "below_score_threshold" if best[0] < .98 else "ambiguous_position_margin" if margin < .03 else None
        # 既存部品と同じ不正metadataの正規化を保持します。
        import math
        seq = frame.sequence if type(frame.sequence) is int else -1
        observed = frame.captured_at if isinstance(frame.captured_at, (int, float)) and math.isfinite(frame.captured_at) else 0.
        return ButtonEvidence(candidate_type="NORMAL_SUMMON" if reason is None else None,
            profile_id=profile_id, evidence_bbox=best[1], search_bbox=(x-64, y-24, w+128, h+48),
            score=best[0], position_runner_up_score=second[0], position_runner_up_bbox=second[1], position_margin=margin,
            frame_seq=seq, observed_at=observed, capture_context=context, detector_sha256=self.sha256,
            profile_sha256=self.profiles[profile_id][2], unknown_reason=reason)

    def match_hand(self, pixels, evidence_bbox):
        """ボタン基準の18x112輪郭のみ。CID/zone/入力点へは転用しません。"""
        self.assert_assets_unchanged()
        x, y = evidence_bbox[0]+27, evidence_bbox[1]+82
        best = 0.
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                xx, yy = x+dx, y+dy
                if 0 <= xx < xx+18 <= 1280 and 0 <= yy < yy+112 <= 720:
                    crop = pixels[yy:yy+112, xx:xx+18]
                    best = max(best, *(m.diagnostic_scores(crop)["true"] for m in self.hand_matchers))
        if self.hand_feature == "raised_card_lines_v1":
            from .hand_geometry import recognize_hand_geometry
            geometry = recognize_hand_geometry(pixels,evidence_bbox)
            self.last_hand_diagnostic = {"rgb_raw_score": best, "rgb_threshold": .98,
                "rgb_not_used_as_gate": True, "geometry": geometry}
            return ("true", 1.) if geometry["passed"] else (None, 0.)
        return ("true", best) if best >= .98 else (None, 0.)
