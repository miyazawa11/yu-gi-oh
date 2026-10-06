from __future__ import annotations

import re
import hashlib
import json
import math
import shutil
import subprocess
import time
from pathlib import Path
from typing import Protocol

import cv2

from .image_io import read_image, write_image
import numpy as np

from .capture import Frame
from .cards import CardDatabase
from .models import Action, ActionType, CardIdentity, GameState, Observation, Phase, Player, PlayerState, UiCoordinateProof, HandSearchCoordinateProof
from .regions import Calibration, Region


class NumericOCR(Protocol):
    def read(self, crop: np.ndarray, maximum: int) -> tuple[int | None, float]: ...


class TesseractOCR:
    def __init__(self, command: str = "tesseract"):
        self.command = shutil.which(command)

    def read(self, crop: np.ndarray, maximum: int, *, deadline: float | None = None) -> tuple[int | None, float]:
        if self.command is None:
            return None, 0
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        # 大きな滑らかな数字の拡大により5200を9200と誤認した回帰を防ぎます。
        # 小さな画像だけ拡大し、2種類の前処理の一致を求めます。
        if gray.shape[0] < 40:
            scale = 40/gray.shape[0]
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        # 数字の形を保ち、余白の多い数値画像は白背景にして OCR を助けます。
        if np.mean(binary) < 127:
            binary = 255 - binary
            gray = 255 - gray
        predictions = []
        for rendering in [gray, binary]:
            rendering = cv2.copyMakeBorder(rendering, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
            predictions.append(self._read_rendering(rendering, maximum, deadline=deadline))
        if predictions[0][0] is None or predictions[0][0] != predictions[1][0]:
            return None, 0
        return predictions[0][0], min(predictions[0][1], predictions[1][1])

    def _read_rendering(self, rendering: np.ndarray, maximum: int, *, deadline: float | None = None) -> tuple[int | None, float]:
        ok, png = cv2.imencode(".png", rendering)
        if not ok:
            return None, 0
        remaining = 3 if deadline is None else min(3, deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("認識・判断の期限に達しました")
        try:
            result = subprocess.run([self.command, "stdin", "stdout", "--psm", "7", "-c", "tessedit_char_whitelist=0123456789", "tsv"], input=png.tobytes(), capture_output=True, timeout=remaining, check=True)
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
    """色を保つ正規化画像の特徴量です。学習済み埋め込みではありません。"""
    return cv2.resize(pixels, (64, 32), interpolation=cv2.INTER_AREA).astype(np.float32)/255


class TemplateMatcher:
    def __init__(self, region: Region, base: Path, allowed_card_ids: set[str] | None = None):
        self.region = region
        self.templates: list[tuple[str, np.ndarray]] = []
        self.asset_hashes = {}
        self.stable_profiles = []
        self.stable_statistics = {}
        for exemplar in region.exemplars:
            if region.kind == "card" and allowed_card_ids is not None and exemplar.label not in allowed_card_ids:
                continue
            path = (base/exemplar.image).resolve()
            # 校正用のローカル画像が指定フォルダーの外を参照するのを防ぎます。
            if not path.is_relative_to(base.resolve()):
                raise ValueError("参照画像は校正ファイルのフォルダー内に配置してください")
            image = read_image(str(path))
            if image is None:
                raise ValueError(f"参照画像を読み込めません: {path}")
            self.asset_hashes[path.relative_to(base.resolve()).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            self.templates.append((exemplar.label, fingerprint(image)))
        if region.kind in {"template", "card", "action"} and not region.exemplars:
            raise ValueError("テンプレート領域には参照画像が必要です")

        if region.feature == "stable_rgb":
            for label in sorted({label for label, _ in self.templates}):
                samples = [feature for key, feature in self.templates if key == label]
                if len(samples) < 10:
                    raise ValueError("stable_rgbはラベルごとに10枚以上の時間変動訓練画像が必要です")
                stack = np.stack(samples)
                prototype = np.median(stack, axis=0)
                deviation = np.max(np.mean(np.abs(stack-prototype), axis=3), axis=0)
                mask = deviation <= .01
                if region.stable_rgb_excluded_rows:
                    mask[region.stable_rgb_excluded_rows, :] = False
                count = int(np.count_nonzero(mask))
                if count < 256:
                    raise ValueError("stable_rgbの安定画素が256未満です。認識を開始できません")
                self.stable_profiles.append((label, prototype, mask))
                self.stable_statistics[label] = {"training_samples": len(samples), "valid_pixels": count,
                    "total_pixels": int(mask.size), "maximum_deviation": .01, "minimum_pixels": 256,
                    "mask_sha256": hashlib.sha256(mask.tobytes()).hexdigest(),
                    "prototype_sha256": hashlib.sha256(prototype.tobytes()).hexdigest()}
                if region.stable_rgb_excluded_rows:
                    self.stable_statistics[label]["excluded_descriptor_rows"] = region.stable_rgb_excluded_rows

    def diagnostic_scores(self, crop: np.ndarray) -> dict[str, float]:
        """失敗資料用の未閾値score。採用結果やconfidenceへ昇格しません。"""
        descriptor = fingerprint(crop)
        if self.region.feature == "stable_rgb":
            return {label: float(1-np.mean(np.abs(descriptor-prototype)[mask]))
                    for label, prototype, mask in self.stable_profiles}
        return {label: max(float(1-np.mean(np.abs(descriptor-template)))
                           for key, template in self.templates if key == label)
                for label in {key for key, _ in self.templates}}

    def match(self, crop: np.ndarray) -> tuple[str | None, float]:
        descriptor = fingerprint(crop)
        scores: dict[str, float] = {}
        if self.region.feature == "rgb":
            for label, template in self.templates:
                score = float(1 - np.mean(np.abs(descriptor-template)))
                scores[label] = max(scores.get(label, 0), score)
        if self.region.feature == "stable_rgb":
            # mask外をゼロ埋めして全体平均しない。有効画素×RGB成分だけが分母。
            scores = {label: float(1-np.mean(np.abs(descriptor-prototype)[mask]))
                      for label, prototype, mask in self.stable_profiles}
        ranked = sorted(scores.items(), key=lambda entry: entry[1], reverse=True)
        if not ranked:
            return None, 0
        label, best = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        if best < self.region.threshold or best-runner_up < self.region.margin:
            return None, 0
        return label, best


class Perception:
    def __init__(self, calibration: Calibration, base: Path, cards: CardDatabase, ocr: NumericOCR | None = None,
                 allowed_card_ids: set[str] | None = None):
        self.calibration, self.cards = calibration, cards
        self.ocr = ocr or TesseractOCR()
        self.matchers = {name: TemplateMatcher(region, base, allowed_card_ids) for name, region in calibration.regions.items() if region.kind in {"template", "card", "action"}}
        self.asset_hashes = {name: matcher.asset_hashes for name, matcher in self.matchers.items()}
        self.stable_statistics = {name: matcher.stable_statistics for name, matcher in self.matchers.items() if matcher.stable_statistics}
        self._validate_semantics()
        self._cache: dict[str, tuple[np.ndarray, object, float]] = {}
        self.cache_hits = 0
        self.recognized_regions = 0
        self.ocr_ms = self.state_build_ms = 0
        self.inspect_goal = None
        self.inspect_registry = self.inspect_detector = None
        self.inspect_client_rect = None
        self.recognition_components = {}
        self.component_files = {}

    def configure_inspect(self, goal, base: Path, config_files=()):
        """専用bookの起動時だけ固定componentを接続します。旧profileは変更しません。"""
        from .detail_name_registry import DetailNameRegistry
        from .action_evidence import ActionEvidenceDetector
        if any(region.stable_rgb_excluded_rows for region in self.calibration.regions.values()) and (
                goal.card_id != "12950" or goal.zone != "monster_2" or goal.inspect_region != "action.inspect_zone"):
            raise ValueError("field除外maskはAsh中央inspect限定です。汎用card占有へ一般化できません")
        if set(self.calibration.recognition_assets) != {"detail_name_registry", "action_evidence_detector"}:
            raise ValueError("inspect profileは詳細registry/detectorの固定resourceが必要です")
        files = {}
        for path in config_files:
            path = Path(path).resolve()
            files[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        for assets in self.asset_hashes.values():
            files.update({(base / name).resolve(): sha for name, sha in assets.items()})
        for name, spec in self.calibration.recognition_assets.items():
            path = (base / spec.path).resolve()
            if hashlib.sha256(path.read_bytes()).hexdigest() != spec.sha256:
                raise ValueError("認識componentの宣言hashが一致しません: " + name)
            files[path] = spec.sha256
        registry_path = (base / self.calibration.recognition_assets["detail_name_registry"].path).resolve()
        detector_path = (base / self.calibration.recognition_assets["action_evidence_detector"].path).resolve()
        self.inspect_registry = DetailNameRegistry(registry_path)
        detector_spec = json.loads(detector_path.read_text(encoding="utf-8"))
        if detector_spec.get("schema") == "normal-inspect-ui-bank-v1":
            if goal.card_id != "12950" or goal.zone != "monster_2" or goal.inspect_region != "action.inspect_zone":
                raise ValueError("既存UI bankはAsh中央normal inspect限定です")
            from .ui_evidence_bank import UiEvidenceBank
            self.inspect_detector = UiEvidenceBank(detector_path)
        else:
            self.inspect_detector = ActionEvidenceDetector(detector_path)
        raw = json.loads(registry_path.read_text(encoding="utf-8"))
        if goal.card_id not in {cid for cid, _, _ in self.inspect_registry.references} or self.cards.get(goal.card_id) is None:
            raise ValueError("目的CIDが固定registryとローカルDBにありません")
        for item in raw["references"]:
            files[(registry_path.parent / item["image"]).resolve()] = item["sha256"]
        provenance = self.inspect_detector.provenance()
        files.update({Path(path): sha for path, sha in provenance["files"].items()})
        for source in Path(__file__).parent.glob("*.py"):
            files[source.resolve()] = hashlib.sha256(source.read_bytes()).hexdigest()
        self.component_files = {str(path): sha for path, sha in files.items()}
        self.recognition_components = {"schema": "normal-inspect-recognition-v1", "goal": goal.model_dump(mode="json"),
            "registry_sha256": self.inspect_registry.sha256, "detector": provenance, "files": self.component_files}
        self.inspect_goal = goal

    def configure_responses(self, goals, base: Path, config_files=()):
        """実画像校正・意味別policy・sourceを同一cohortへ固定します。"""
        files = dict(self.component_files)
        for path in config_files:
            path = Path(path).resolve()
            files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        for assets in self.asset_hashes.values():
            files.update({str((base / name).resolve()): sha for name, sha in assets.items()})
        for path in Path(__file__).parent.glob("*.py"):
            files[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
        caption_provenance = None
        caption_path = base / "cancel-caption.json"
        self.cancel_caption = None
        if caption_path.is_file():
            from .cancel_caption import CancelCaptionDetector, PARAMETERS
            if self.calibration.viewport.model_dump() != {"x":0.,"y":0.,"width":1.,"height":1.}:
                raise ValueError("Cancel captionはnative全client校正のみです")
            self.cancel_caption = CancelCaptionDetector(caption_path)
            for goal in goals:
                region = self.calibration.regions.get(goal.cancel_region)
                box = PARAMETERS["click_bbox"]
                if (region is None or region.kind != "action" or region.card_id is not None or region.target is not None
                        or any(abs(a-b)>1e-6 for a,b in zip(
                            [region.rect.x,region.rect.y,region.rect.width,region.rect.height],
                            [box[0]/1280,box[1]/720,box[2]/1280,box[3]/720]))):
                    raise ValueError("Cancel文字bboxと入力bboxの対応が固定校正と一致しません")
            caption_provenance = self.cancel_caption.provenance()
            files.update(caption_provenance["files"])
        self.component_files = files
        self.response_goals = tuple(goals)
        self.observed_self_draw = any(g.evidence_mode == "observed_self_draw" for g in goals)
        self.recognition_components = {**self.recognition_components,
            "schema": "solo-basic-recognition-v1", "response_goals": [g.model_dump(mode="json") for g in goals],
            "files": files}
        if caption_provenance:
            self.recognition_components["cancel_caption"] = caption_provenance
        self.draw_overlay = None
        draw_path = base / "draw-overlay.json"
        if draw_path.is_file():
            from .draw_outcome import DrawOverlayDetector
            if (self.calibration.viewport.model_dump() != {"x":0.,"y":0.,"width":1.,"height":1.}
                    or not any(goal.outcome == "self_draw" for goal in goals)):
                raise ValueError("Draw overlayはnative self_draw応答profileのみです")
            self.draw_overlay = DrawOverlayDetector(draw_path)
            provenance = self.draw_overlay.provenance()
            files.update(provenance["files"])
            self.recognition_components["draw_overlay"] = provenance
        if self.observed_self_draw and self.draw_overlay is None:
            raise ValueError("直接selfDraw観測には固定word/selfblue componentが必要です")

    def _validate_semantics(self):
        numeric_names = {"self.lp", "opponent.lp", "self.hand_count", "opponent.hand_count", "turn"}
        for name, region in self.calibration.regions.items():
            labels = [e.label for e in region.exemplars]
            if region.kind == "unobserved":
                continue
            if name in numeric_names:
                if region.kind not in {"number", "template"}:
                    raise ValueError(f"数値項目に未対応の認識方式が指定されています: {name}")
                maximum = 999999 if name.endswith(".lp") else 999 if name == "turn" else 60
                if any(not label.isdecimal() or int(label) > maximum for label in labels):
                    raise ValueError(f"数値テンプレートのラベルが不正です: {name}")
            elif name == "phase":
                if region.kind != "template":
                    raise ValueError("フェイズ認識にはテンプレートが必要です")
                for label in labels:
                    Phase(label)
            elif name == "turn_player":
                if region.kind != "template":
                    raise ValueError("ターンプレイヤー認識にはテンプレートが必要です")
                for label in labels:
                    Player(label)
            elif name == "game.terminal":
                if region.kind != "template" or any(label not in {"ended", "active"} for label in labels):
                    raise ValueError("game.terminal には template と ended / active のラベルが必要です")
            elif name == "ui.prompt":
                if region.kind != "template" or any(not label for label in labels):
                    raise ValueError("ui.promptには空でない識別名のtemplateが必要です")
            elif name == "ui.animation":
                if region.kind != "template" or any(label not in {"playing", "idle"} for label in labels):
                    raise ValueError("ui.animationにはplaying/idleのtemplateが必要です")
            elif name.startswith("fact."):
                if region.kind != "template" or not labels or any(not label for label in labels):
                    raise ValueError("展開条件には空でない識別値のtemplateが必要です")
            elif name.startswith("card_state."):
                if region.kind != "template" or any(label not in {"face_up", "face_down", "selectable", "selected"} for label in labels):
                    raise ValueError("カード状態にはface_up/face_down/selectable/selectedのtemplateが必要です")
            elif name.startswith("action."):
                if region.kind != "action":
                    raise ValueError("操作項目には操作 UI のテンプレートが必要です")
                for label in labels:
                    ActionType(label)
            elif re.fullmatch(r"(self|opponent)\.zones\.[a-zA-Z0-9_]+", name):
                if region.kind != "card":
                    raise ValueError("ゾーンのカード識別にはカードのテンプレートが必要です")
            else:
                raise ValueError(f"未対応の観測領域です: {name}")

    def configure_hand_search(self,goal,base):
        from .hand_search import HandSearchVision
        self.hand_goal=goal;self.hand_vision=HandSearchVision(base/"hand-search.json")
        provenance=self.hand_vision.provenance()
        if goal.own_chain_mode=="parent_activation_ui":
            from .cancel_caption import CancelCaptionDetector
            self.hand_cancel_caption=CancelCaptionDetector(base/"cancel-caption.json")
            provenance["own_chain_cancel_caption"]=self.hand_cancel_caption.provenance()
            provenance["files"].update(self.hand_cancel_caption.files)
        self.component_files.update(provenance["files"])
        self.recognition_components.update(hand_search={**provenance,"goal":goal.model_dump(mode="json")},files=self.component_files)
        self.hand_context=None

    def _hand_search_observations(self,frame,observed,actions,proposed,context):
        vision=self.hand_vision;goal=self.hand_goal;static=vision.recognize(frame)
        if context is not None:self.hand_context=context
        context=self.hand_context
        if context is not None and (context.get("result") is not None or context.get("hand_search_confirmation")!=goal.model_dump(mode="json")):
            context=None;self.hand_context=None
        episode=vision.observe(frame,context,static)
        self.hand_episode=episode
        def fact(key,value,positive=True):
            observed["fact."+key]=Observation(value=value,confidence=1 if positive else 0,
                source="hand_search:"+vision.sha256,observed_at=frame.captured_at)
        fact(goal.detail_fact,static["detail_cid"],static["detail_cid"] is not None)
        layout=static["source_layout"]
        source_ready=layout is not None and not static["gy_panel"]
        fact(goal.source_ready_fact,"true" if source_ready else None,source_ready)
        fact("hand_search.layout",layout,layout is not None)
        own=static["own_chain"] and context is not None and len(context.get("steps",[]))>=1
        fact(goal.own_chain_fact,"true" if own else None,own)
        permission=False
        if own and goal.own_chain_mode=="parent_activation_ui":
            from .hand_search import activation_parent_valid
            caption=self.hand_cancel_caption.detect(frame.pixels)
            contradictions=[observed.get("fact."+key) for key in ["response.prompt.opponent_turn_end","response.prompt.opponent_summon_success"]]
            permission=(caption.passed and activation_parent_valid(context,goal,frame,vision.sha256,
                logical_action=getattr(self,"hand_logical_action",None))
                and not static["gy_panel"] and not any(o is not None and o.value=="true" and o.confidence>=.98 for o in contradictions))
            fact("hand_search.own_chain_permission","true" if permission else None,permission)
            observed["fact.hand_search.own_chain_caption"]=Observation(value=json.dumps({"score":caption.score,"config_sha256":caption.config_sha256,
                "click_point":caption.click_point}),confidence=0,source="diagnostic:not_a_legal_fact",observed_at=frame.captured_at)
        blank=observed.get("fact.inspect_context.detail_blank")
        ready=bool(episode and not episode["failed"] and episode["ready"] and not static["gy_panel"] and not static["own_chain"]
            and static["detail_cid"] is None and blank is not None and blank.value=="true" and blank.confidence>=.98
            and blank.observed_at==frame.captured_at and blank.source.startswith("template:"))
        selected=bool(episode and not episode["failed"] and episode["handoff"] and context is not None
            and len(context.get("steps",[]))==3 and episode.get("current_selected_geometry") is not None
            and static["detail_cid"]=="13906" and not static["gy_panel"] and not static["own_chain"])
        fact(goal.result_ready_fact,"true" if ready else None,ready)
        fact(goal.result_selected_fact,"true" if selected else None,selected)
        observed["fact.hand_search.diagnostic"]=Observation(value=json.dumps(static,sort_keys=True),confidence=0,
            source="diagnostic:not_a_legal_fact",observed_at=frame.captured_at)
        scene="effect_menu" if source_ready else "own_chain" if own else "result_selected" if selected else "result_ready" if ready else None
        main=observed.get("fact.inspect_context.main1")
        if permission:
            # 現在phase/player/animationはunknownのまま。専用任意UIとactiveだけを観測。
            for name,value in [("ui.prompt","hand.dragondark.own_chain"),("game.terminal",False)]:
                proposed.setdefault(name,[]).append(Observation(value=value,confidence=1,source="hand_search:"+vision.sha256,observed_at=frame.captured_at))
            actions.append(Action(type="CANCEL",confidence=1,source_region=goal.cancel_region,observed_at=frame.captured_at))
        if (scene and not (static["own_chain"] and goal.own_chain_mode=="parent_activation_ui")
                and main is not None and main.value=="true" and main.confidence>=.98 and main.observed_at==frame.captured_at):
            values=[("phase",Phase.MAIN1),("turn_player",Player.SELF),("game.terminal",False),
                    ("ui.prompt","hand.dragondark."+scene)]
            if scene in {"effect_menu","own_chain"}:values.append(("ui.animation",False))
            for name,value in values:
                proposed.setdefault(name,[]).append(Observation(value=value,confidence=min(1,main.confidence),
                    source="hand_search:"+vision.sha256,observed_at=frame.captured_at))
            live=frame.capture_source=="live_mss" and frame.capture_rect==self.inspect_client_rect
            if source_ready:
                spec=vision.config["layouts"][layout];box=tuple(spec["effect_box"]);point=tuple(spec["effect_point"])
                proof=HandSearchCoordinateProof(action_type="ACTIVATE",layout_id=layout,frame_seq=frame.sequence,
                    observed_at=frame.captured_at,client_rect=self.inspect_client_rect,evidence_bbox=box,point=point,profile_sha256=vision.sha256) if live else None
                actions.append(Action(type="ACTIVATE",card_id="13906",confidence=1,source_region=goal.activate_region,
                    observed_at=frame.captured_at,hand_search_proof=proof))
            if own and not permission:actions.append(Action(type="CANCEL",confidence=1,source_region=goal.cancel_region,observed_at=frame.captured_at))
            if ready and not selected:
                visible=episode["current_ready_geometry"]
                box=tuple(visible["bbox"]);point=tuple(visible["point"])
                proof=HandSearchCoordinateProof(action_type="SELECT_CARD",layout_id=episode["layout"],frame_seq=frame.sequence,
                    observed_at=frame.captured_at,client_rect=self.inspect_client_rect,evidence_bbox=box,point=point,profile_sha256=vision.sha256) if live else None
                actions.append(Action(type="SELECT_CARD",card_id="13906",target="self.hand.received",confidence=1,
                    source_region=goal.inspect_region,observed_at=frame.captured_at,hand_search_proof=proof))

    def process(self, frame: Frame, *, deadline: float | None = None, verification_scope=None, hand_episode_context=None) -> GameState:
        if verification_scope is not None:
            from .strategy_rules import LogicalResponseDecline
            if (not isinstance(verification_scope, LogicalResponseDecline)
                    or verification_scope not in getattr(self, "response_goals", ())):
                raise ValueError("認識省略scopeは固定bookに宣言された応答辞退だけです")
        if self.inspect_goal is None and any(r.stable_rgb_excluded_rows for r in self.calibration.regions.values()):
            raise ValueError("field除外maskはconfigure済みAsh inspect profileのみで認識できます")
        recognition_start = time.perf_counter()
        self.stage_spans = []
        crops = self.calibration.crop_regions(frame.pixels)
        observed: dict[str, Observation] = {}
        actions: list[Action] = []
        self.cache_hits = self.recognized_regions = 0
        self.ocr_ms = 0
        caption = getattr(self, "cancel_caption", None)
        caption_goals = getattr(self, "response_goals", ()) if caption else ()
        caption_names = {name for goal in caption_goals for name in (goal.cancel_region, "fact."+goal.cancel_fact)}
        for name, region in self.calibration.regions.items():
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("認識・判断の期限に達しました")
            value, confidence = None, 0.0
            hand_goal=getattr(self,"hand_goal",None)
            if hand_goal is not None and name in {hand_goal.activate_region,hand_goal.cancel_region,hand_goal.inspect_region}:
                continue
            if name in caption_names:
                # 旧RGB参照は固定資産として保持、新経路の採用ゲートには使いません。
                continue
            cached = self._cache.get(name)
            if cached is not None and np.array_equal(cached[0], crops[name]):
                _, value, confidence = cached
                self.cache_hits += 1
            elif region.kind == "number":
                ocr_started = time.perf_counter()
                maximum = 999999 if name.endswith(".lp") else 999 if name == "turn" else 60
                if isinstance(self.ocr, TesseractOCR):
                    value, confidence = self.ocr.read(crops[name], maximum, deadline=deadline)
                else:
                    value, confidence = self.ocr.read(crops[name], maximum)
                self.ocr_ms += (time.perf_counter() - ocr_started)*1000
            elif name in self.matchers:
                value, confidence = self.matchers[name].match(crops[name])
            if deadline is not None and time.monotonic() >= deadline:
                # 打ち切った認識結果をキャッシュへ保存しません。
                raise TimeoutError("認識・判断の期限に達しました")
            if cached is None or not np.array_equal(cached[0], crops[name]):
                self._cache[name] = (crops[name].copy(), value, confidence)
                self.recognized_regions += 1
            if region.kind == "action":
                if value is not None and (self.inspect_goal is None or name != self.inspect_goal.summon_region):
                    actions.append(Action(type=ActionType(value), card_id=region.card_id,
                                          target=region.target, confidence=confidence,
                                          source_region=name, observed_at=frame.captured_at))
                continue
            if name.startswith(("self.zones.", "opponent.zones.")) and value is not None:
                card = self.cards.get(str(value))
                if card is None:
                    value, confidence = None, 0
                else:
                    value = CardIdentity(card_id=card.card_id, name=card.name, card_type=card.type)
            elif name == "phase" and value is not None:
                value = Phase(value)
            elif name == "game.terminal" and value is not None:
                value = value == "ended"
            elif name == "turn_player" and value is not None:
                value = Player(value)
            elif name == "ui.animation" and value is not None:
                value = value == "playing"
            elif name == "ui.prompt" or name.startswith(("card_state.", "fact.")):
                pass
            elif value is not None:
                value = int(value)
            observed[name] = Observation(value=value, confidence=confidence, source=f"{region.kind}:{name}", observed_at=frame.captured_at)

        detected_button = None
        if self.inspect_goal is not None:
            from .action_evidence import CaptureContext
            detail = self.inspect_registry.recognize(frame)
            observed["fact." + self.inspect_goal.detail_card_fact] = Observation(
                value=detail.cid, confidence=detail.score if detail.cid is not None else 0,
                source="detail_registry:" + detail.registry_sha256, observed_at=frame.captured_at)
            live = (self.inspect_client_rect is not None and frame.capture_source == "live_mss"
                    and frame.capture_rect == self.inspect_client_rect)
            context = CaptureContext(mode="live_capture" if live else "offline_saved_image",
                capture_source="MSS" if live else "saved_image",
                client_rect=self.inspect_client_rect,
                captured_at_clock="monotonic" if live else "unspecified_zero_not_capture_time",
                frame_seq_semantics="capture_sequence" if live else "manifest_index_not_capture_sequence")
            bank_span = {"stage":"normal_ui_bank","start":time.perf_counter(),"end":None,
                "skipped_search":verification_scope is not None,
                "verification_scope":verification_scope.model_dump(mode="json") if verification_scope is not None else None}
            self.stage_spans.append(bank_span)
            try:
                if verification_scope is not None:
                    # 探索だけを省略。固定asset検査と他の認識/矛盾検査は維持します。
                    self.inspect_detector.assert_assets_unchanged()
                    for key in [self.inspect_goal.summon_enabled_fact,self.inspect_goal.hand_selected_fact]:
                        observed["fact."+key] = Observation(source="not_in_response_verification_scope",observed_at=frame.captured_at)
                else:
                    detected_button = self.inspect_detector.recognize(frame, context, "solar-menu-v2")
                    observed["fact." + self.inspect_goal.summon_enabled_fact] = Observation(
                        value="true" if detected_button.candidate_type is not None else None,
                        confidence=detected_button.score if detected_button.candidate_type is not None else 0,
                        source="readonly_detector:" + detected_button.detector_sha256, observed_at=frame.captured_at)
            except Exception as exc:
                bank_span["error"] = type(exc).__name__
                raise
            finally:
                bank_span["end"] = time.perf_counter()
            if detected_button is not None and detected_button.candidate_type is not None:
                # カードIDではなく、検出menuに対する既知の手札選択輪郭を照合します。
                hand_name = "fact." + self.inspect_goal.hand_selected_fact
                hand_region = self.calibration.regions[hand_name]
                box = hand_region.rect
                anchor_x, anchor_y, _, _ = detected_button.evidence_bbox
                x = math.floor(box.x * 1280) + anchor_x - 380
                y = math.floor(box.y * 720) + anchor_y - 497
                width = math.ceil((box.x + box.width) * 1280) - math.floor(box.x * 1280)
                height = math.ceil((box.y + box.height) * 720) - math.floor(box.y * 720)
                label, score = (None, 0)
                if 0 <= x < x+width <= 1280 and 0 <= y < y+height <= 720:
                    label, score = self.matchers[hand_name].match(frame.pixels[y:y+height, x:x+width])
                if hasattr(self.inspect_detector, "match_hand"):
                    label, score = self.inspect_detector.match_hand(frame.pixels, detected_button.evidence_bbox)
                hand_source = "template:" + hand_name + ":relative_to_detected_menu"
                if getattr(self.inspect_detector, "hand_geometry_sha256", None):
                    hand_source = "geometry:" + self.inspect_detector.hand_geometry_sha256
                    observed["fact.inspect_context.hand_source_diagnostic"] = Observation(
                        value=json.dumps(self.inspect_detector.last_hand_diagnostic, sort_keys=True), confidence=0,
                        source="diagnostic:not_a_legal_fact", observed_at=frame.captured_at)
                observed[hand_name] = Observation(value=label, confidence=score if label is not None else 0,
                    source=hand_source, observed_at=frame.captured_at)
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("認識・判断の期限に達しました")

        # 陽性のANDのみ。根拠不明・失効・矛盾から既定値を生成しません。
        proposed = {}
        if caption:
            result = caption.detect(frame.pixels)
            for goal in caption_goals:
                observed["fact."+goal.cancel_fact] = Observation(value="true" if result.passed else None,
                    confidence=1 if result.passed else 0, source="caption_shape:"+caption.sha256,
                    observed_at=frame.captured_at)
                if result.passed:
                    actions.append(Action(type=ActionType.CANCEL,confidence=1,source_region=goal.cancel_region,
                                          observed_at=frame.captured_at))
            observed["fact.response.caption_diagnostic"] = Observation(value=json.dumps({
                "score":result.score,"acceptance_score":.85,"yellow_pixels":result.yellow_pixels,
                "caption_bbox":result.caption_bbox,"click_bbox":result.click_bbox,"click_point":result.click_point,
                "config_sha256":result.config_sha256,"binary_confidence":"predicate, not probability"},sort_keys=True),
                confidence=0,source="diagnostic:not_a_legal_fact",observed_at=frame.captured_at)
        draw_overlay = getattr(self, "draw_overlay", None)
        direct_draw = getattr(self, "observed_self_draw", False)
        original_ui = any((ob:=observed.get(name)) is not None and ob.value == "true" and ob.confidence >= .98
            and ob.observed_at == frame.captured_at for name in ["fact.response.prompt.opponent_summon_success",
                "fact.response.prompt.opponent_turn_end","fact.response.cancel_enabled.opponent_summon_success",
                "fact.response.cancel_enabled.opponent_turn_end"])
        if direct_draw:
            # 固定床RGBを完了根拠として使わず、未閾値値は診断に残します。
            floor_name = "fact.response.modal_absent"
            floor = observed.get(floor_name)
            if floor is not None:
                observed[floor_name] = floor.model_copy(update={"confidence":0,"source":"diagnostic:background_not_completion"})
                observed["fact.response.modal_background_diagnostic"] = Observation(value=json.dumps({
                    "raw_scores":self.matchers[floor_name].diagnostic_scores(crops[floor_name]),
                    "semantic_use":"diagnostic_only_not_modal_absence"},sort_keys=True),confidence=0,
                    source="diagnostic:not_a_legal_fact",observed_at=frame.captured_at)
            if original_ui:
                observed["fact.response.outcome.self_draw"] = Observation(source="conflicting_positive_response_ui",observed_at=frame.captured_at)
        if draw_overlay:
            result = draw_overlay.detect(frame.pixels)
            # 旧overlay無しDraw陽性は保持。新modeはmodal無しとのANDだけです。
            absent = observed.get("fact.response.modal_absent")
            old_draw = observed.get("fact.response.outcome.self_draw")
            completed_evidence = (not original_ui) if direct_draw else (absent is not None and absent.value == "true"
                and absent.confidence >= .98 and absent.observed_at == frame.captured_at)
            if (result.passed and completed_evidence and (old_draw is None or old_draw.value is None)):
                observed["fact.response.outcome.self_draw"] = Observation(value="true", confidence=1,
                    source="draw_overlay:"+draw_overlay.sha256, observed_at=frame.captured_at)
            observed["fact.response.draw_overlay_diagnostic"] = Observation(value=json.dumps({
                "word_score":result.word_score,"self_blue_ratio":result.self_blue_ratio,
                "config_sha256":result.config_sha256,"binary_confidence":"predicate, not probability"},sort_keys=True),
                confidence=0,source="diagnostic:not_a_legal_fact",observed_at=frame.captured_at)
            if direct_draw and not original_ui:
                direct = observed.get("fact.response.outcome.self_draw")
                if (direct is not None and direct.value == "true" and direct.confidence >= .98
                        and direct.observed_at == frame.captured_at and result.self_blue_ratio >= .15):
                    # word+blue/旧Draw陽性の専用mode。prompt/animationはemitしません。
                    for name,value in [("phase",Phase.DRAW),("turn_player",Player.SELF),("game.terminal",False)]:
                        proposed.setdefault(name,[]).append(Observation(value=value,confidence=direct.confidence,
                            source="observed_self_draw:"+draw_overlay.sha256,observed_at=frame.captured_at))
        if getattr(self,"hand_vision",None) is not None:
            self._hand_search_observations(frame,observed,actions,proposed,hand_episode_context)
        for context in self.calibration.composites:
            evidence = [observed.get(name) for name in context.when]
            if not all(o is not None and o.value == label and o.confidence >= .98
                       and o.observed_at == frame.captured_at
                       for o, label in zip(evidence, context.when.values())):
                continue
            for name, value in context.emit.items():
                if name == "phase": value = Phase(value)
                elif name == "turn_player": value = Player(value)
                elif name == "ui.animation": value = value == "playing"
                elif name == "game.terminal": value = value == "ended"
                proposed.setdefault(name, []).append(Observation(value=value, confidence=min(o.confidence for o in evidence),
                    source="composite:" + context.id, observed_at=frame.captured_at))
        for name, candidates in proposed.items():
            direct = observed.get(name)
            if direct is not None and direct.value is not None:
                candidates.append(direct)
            if len({o.value for o in candidates}) != 1:
                observed[name] = Observation(source="conflicting_positive_evidence", observed_at=frame.captured_at)
            else:
                observed[name] = min(candidates, key=lambda o: o.confidence)

        def obs(name):
            return observed.get(name, Observation(observed_at=frame.captured_at))

        def player(side):
            prefix = side+".zones."
            return PlayerState(lp=obs(side+".lp"), hand_count=obs(side+".hand_count"), zones={key[len(prefix):]: value for key, value in observed.items() if key.startswith(prefix)})

        build_started = time.perf_counter()
        state_build_start = time.perf_counter()
        self.stage_spans.append({"stage": "recognition", "start": recognition_start, "end": state_build_start})
        state = GameState(sequence=frame.sequence, captured_at=frame.captured_at, media_time=frame.media_time, turn=obs("turn"), turn_player=obs("turn_player"), phase=obs("phase"), terminal=obs("game.terminal"), prompt=obs("ui.prompt"), animation=obs("ui.animation"), card_states={k.removeprefix("card_state."): v for k,v in observed.items() if k.startswith("card_state.")}, self=player("self"), opponent=player("opponent"), visible_actions=actions)
        self.state_build_ms = (time.perf_counter() - build_started)*1000
        state = state.model_copy(update={"facts": {k.removeprefix("fact."): v for k, v in observed.items() if k.startswith("fact.")}})
        if self.inspect_goal is not None and detected_button is not None and detected_button.candidate_type is not None:
            goal = self.inspect_goal
            required = {goal.detail_card_fact: goal.card_id, goal.hand_selected_fact: "true",
                        goal.summon_enabled_fact: "true", f"zone.self.{goal.zone}.occupancy": "empty"}
            if (state.prompt.value == "card.menu" and state.prompt.observed_at == frame.captured_at
                    and state.phase.value == Phase.MAIN1 and state.turn_player.value == Player.SELF
                    and all((o := state.facts.get(key)) is not None and o.value == value and o.confidence >= .98
                            and o.observed_at == frame.captured_at for key, value in required.items())):
                proof = (UiCoordinateProof(frame_seq=frame.sequence, observed_at=frame.captured_at,
                    client_rect=self.inspect_client_rect, evidence_bbox=detected_button.evidence_bbox,
                    score=detected_button.score, position_margin=detected_button.position_margin,
                    detector_sha256=detected_button.detector_sha256, profile_sha256=detected_button.profile_sha256,
                    profile_id=detected_button.profile_id) if live else None)
                # A1のusable_for_inputは変更せず、別profileのUI/context証拠をANDで結びます。
                action = Action(type=ActionType.NORMAL_SUMMON, card_id=goal.card_id, confidence=min(
                    detected_button.score, *(state.facts[key].confidence for key in required)),
                    source_region=goal.summon_region, observed_at=frame.captured_at, coordinate_proof=proof)
                state = state.model_copy(update={"visible_actions": [*state.visible_actions, action]})
        self.stage_spans.append({"stage": "state_build", "start": state_build_start, "end": time.perf_counter()})
        return state
