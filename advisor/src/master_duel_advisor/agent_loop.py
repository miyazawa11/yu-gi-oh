"""明示的な上限と観測確認を持つ反復型 UI Agent Loop。"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from .capture import Frame, LiveCaptureSource
from .image_io import write_image
from .models import Action, GameState
from .pipeline import FrameGate, Pipeline, save_json
from .perception import Perception
from .telemetry import ActionTelemetry, MeasuredCapture
from .safety import ControlState, DesktopControl, GuardedClicker, InputBlocked, WindowsDesktop


class Capture(Protocol):
    def read(self) -> Frame | None: ...
    def close(self) -> None: ...


class Clicker(Protocol):
    def click(self, x: int, y: int) -> None: ...


class StopSignal(Protocol):
    def stopped(self) -> bool: ...


@dataclass(frozen=True)
class LoopLimits:
    max_seconds: float = 300
    max_actions: int = 100
    min_confidence: float = 0.98
    max_retries: int = 1
    max_same_action: int = 3
    settle_seconds: float = 0
    verify_seconds: float = 3
    verify_poll_seconds: float = 0.05
    min_image_change: float = 0.005
    max_observation_age: float = 1.0

    def __post_init__(self):
        if self.max_seconds <= 0 or self.max_actions <= 0 or not 0 < self.min_confidence <= 1:
            raise ValueError("実行時間・操作回数は正、信頼度は0〜1で指定してください")
        if self.max_retries < 0 or self.max_same_action < 1 or self.verify_seconds <= 0:
            raise ValueError("再試行・繰り返し・確認の上限が不正です")
        if (self.settle_seconds < 0 or self.verify_poll_seconds <= 0
                or self.max_observation_age <= 0 or not 0 <= self.min_image_change <= 1
                or not all(np.isfinite(v) for v in [self.max_seconds, self.settle_seconds,
                           self.verify_seconds, self.verify_poll_seconds, self.max_observation_age])):
            raise ValueError("待機・確認周期・観測期限は有限の適切な値で指定してください")


class Recovery:
    """失敗後は最新画面から再認識し、古い座標を再利用しません。"""
    def next_frame(self, capture: Capture) -> Frame | None:
        return capture.read()


class Verification:
    def __init__(self, limits: LoopLimits):
        self.limits = limits

    def changed(self, before: np.ndarray, after: np.ndarray) -> bool:
        if before.shape != after.shape:
            return True
        a = before.astype(np.float32) / 255
        b = after.astype(np.float32) / 255
        return float(np.mean(np.abs(a - b))) >= self.limits.min_image_change

    def expected(self, before_image: np.ndarray, after_image: np.ndarray,
                 before_state: GameState, after_state: GameState, action: Action) -> bool:
        """画素だけの演出変化で成功とせず、認識状態または候補 UI の変化を求めます。"""
        if not self.changed(before_image, after_image):
            return False
        def value(observation):
            return observation.value
        fields = [(before_state.turn, after_state.turn),
                  (before_state.prompt, after_state.prompt),
                  (before_state.phase, after_state.phase),
                  (before_state.turn_player, after_state.turn_player),
                  (before_state.self.lp, after_state.self.lp),
                  (before_state.opponent.lp, after_state.opponent.lp),
                  (before_state.self.hand_count, after_state.self.hand_count)]
        if any(value(a) is not None and value(b) is not None and value(a) != value(b)
               and min(a.confidence,b.confidence) >= self.limits.min_confidence
               and b.observed_at == after_state.captured_at
               for a,b in fields):
            return True
        # 選択済み枚数や対象だけが変わり、promptとボタンが同じ場合も確認する。
        if any(before_state.facts[key].value is not None and after_state.facts[key].value is not None
               and before_state.facts[key].value != after_state.facts[key].value
               and min(before_state.facts[key].confidence, after_state.facts[key].confidence) >= self.limits.min_confidence
               and after_state.facts[key].observed_at == after_state.captured_at
               for key in before_state.facts.keys() & after_state.facts.keys()):
            return True
        for side in ["self", "opponent"]:
            old, new = getattr(before_state, side).zones, getattr(after_state, side).zones
            if any(old[name].value != new[name].value and old[name].value is not None
                   and new[name].value is not None
                   and min(old[name].confidence,new[name].confidence) >= self.limits.min_confidence
                   and new[name].observed_at == after_state.captured_at
                   for name in old.keys() & new.keys()):
                return True
        before_actions = {(a.type, a.source_region, a.card_id, a.target) for a in before_state.visible_actions}
        after_actions = {(a.type, a.source_region, a.card_id, a.target) for a in after_state.visible_actions
                         if a.confidence >= self.limits.min_confidence and a.observed_at == after_state.captured_at}
        # 認識喪失や演出中の空候補だけでは次の手順へ進めません。
        return bool(after_actions) and before_actions != after_actions


class AgentLoop:
    def __init__(self, capture: Capture, pipeline: Pipeline, calibration, clicker: Clicker,
                 stop_signal: StopSignal, output: Path, screen_rect: tuple[int,int,int,int],
                 limits: LoopLimits = LoopLimits(), recovery: Recovery | None = None,
                 verification: Verification | None = None, clock=time.monotonic,
                 sleep=time.sleep, telemetry_mode="unclassified", benchmark_trials=None,
                 run_purpose="pilot", cohort_manifest=None, cohort_slot=None, execution_conditions=None):
        self.telemetry = ActionTelemetry(output, mode=telemetry_mode, trials=benchmark_trials,
                                         run_purpose=run_purpose, cohort_manifest=cohort_manifest, cohort_slot=cohort_slot)
        self.telemetry.configure(calibration=calibration.model_dump(mode="json"),
                                 template_assets=getattr(pipeline.perception, "asset_hashes", {}),
                                 stable_features=getattr(pipeline.perception, "stable_statistics", {}),
                                 strategy=getattr(getattr(pipeline, "planner", None), "book", None).model_dump(mode="json")
                                 if getattr(getattr(pipeline, "planner", None), "book", None) else None,
                                 limits=asdict(limits), capture={"type": type(capture).__name__, "rect": screen_rect},
                                 execution_conditions=execution_conditions)
        self.telemetry.configure(recognition_components=getattr(pipeline.perception, "recognition_components", {}))
        self.telemetry.freeze_provenance()
        self.clicker, self.stop_signal, self.output = clicker, stop_signal, output
        self.screen_rect, self.limits = screen_rect, limits
        self.inspection_goal = getattr(pipeline.perception, "inspect_goal", None)
        guarded_scope = (self.inspection_goal is not None or bool(getattr(pipeline.perception, "response_goals", ()))
                         or getattr(pipeline.perception,"hand_goal",None) is not None)
        self.inspection_live_bound = bool(guarded_scope and isinstance(capture, LiveCaptureSource)
                                          and capture.backend == "mss" and tuple(capture.rect) == tuple(screen_rect)
                                          and telemetry_mode == "live_autonomous")
        if self.inspection_live_bound:
            pipeline.perception.inspect_client_rect = tuple(screen_rect)
        self.capture, self.pipeline, self.calibration = MeasuredCapture(capture, self.telemetry,
            activity_probe=self.clicker.input_epoch if self.inspection_live_bound else None), pipeline, calibration
        self.current_input_epoch = None
        self.recovery, self.verification = recovery or Recovery(), verification or Verification(limits)
        self.clock, self.sleep = clock, sleep
        self.repeat_key = None
        self.repeat_count = 0
        self.completed = 0
        self.deadline = None
        self.gate = FrameGate(calibration=calibration, refresh_seconds=.5)
        self.pending_frame = None
        self.pending_state = None
        self.decision_frame = None
        self.decision_state = None
        self.decision_capture_start = None
        self.latencies: list[float] = []
        self.control_state = ControlState.OBSERVING
        self.last_runtime_frame = self.last_runtime_state = self.last_runtime_recognized = None

    def _remember_runtime(self, frame, state=None):
        """実readの参照だけを保持。保存画像を再取得したり取得時計を更新しません。"""
        if frame is not None:
            self.last_runtime_frame, self.last_runtime_state = frame, state
            if state is not None:self.last_runtime_recognized = (frame,state)

    @property
    def guarded_scope(self):
        return self.inspection_goal is not None or bool(getattr(self.pipeline.perception, "response_goals", ())) or getattr(self.pipeline.perception,"hand_goal",None) is not None

    def _coordinates(self, action: Action, image_shape, *, frame=None, state=None) -> tuple[int,int]:
        region = self.calibration.regions.get(action.source_region)
        if region is None or region.kind != "action":
            raise ValueError("候補に対応する校正済み action 領域がありません")
        if self.guarded_scope:
            if (not self.inspection_live_bound or frame is None or state is None
                    or frame.capture_source != "live_mss" or frame.capture_rect != tuple(self.screen_rect)
                    or frame.input_epoch is None or state.sequence != frame.sequence
                    or state.captured_at != frame.captured_at or action.observed_at != frame.captured_at
                    or tuple(image_shape) != (720, 1280, 3)
                    or not 0 <= self.clock() - frame.captured_at <= self.limits.max_observation_age):
                raise ValueError("inspect候補の実MSS取得・同frame・client・鮮度証拠が不足しています")
            if self.inspection_goal is not None and action.type.value == "NORMAL_SUMMON":
                proof = action.coordinate_proof
                detector = self.pipeline.perception.inspect_detector
                if (proof is None or proof.frame_seq != frame.sequence or proof.observed_at != frame.captured_at
                        or proof.client_rect != tuple(self.screen_rect) or proof.profile_id != "solar-menu-v2"
                        or proof.detector_sha256 != detector.sha256
                        or proof.profile_sha256 != detector.profiles[proof.profile_id][2]
                        or action.source_region != self.inspection_goal.summon_region
                        or action.card_id != self.inspection_goal.card_id):
                    raise ValueError("動的召喚座標の固定profile/同frame証拠が一致しません")
                x, y, w, h = proof.evidence_bbox
                if (w, h) != (74, 79) or not (316 <= x <= 444 and 473 <= y <= 521):
                    raise ValueError("動的召喚座標が検証対象の探索範囲外です")
                return self.screen_rect[0] + round(x + w/2), self.screen_rect[1] + round(y + h/2)
            hand_goal=getattr(self.pipeline.perception,"hand_goal",None)
            if (hand_goal is not None and hand_goal.own_chain_mode=="parent_activation_ui"
                    and action.source_region==hand_goal.cancel_region):
                from .hand_search import activation_parent_valid
                active=self.telemetry.active;steps=(active or {}).get("steps",[])
                rule=self.pipeline.planner.rule_for(action)
                vision=self.pipeline.perception.hand_vision
                caption=self.pipeline.perception.hand_cancel_caption
                caption.assert_unchanged()
                permission=state.facts.get("hand_search.own_chain_permission")
                if (not active or len(steps)!=2 or steps[1].get("input_sent") is not None
                        or steps[1].get("action")!=action.model_dump(mode="json")
                        or steps[1].get("before_sequence")!=frame.sequence
                        or rule is None or rule.logical_hand_search_confirmation!=hand_goal
                        or permission is None or permission.source!="hand_search:"+vision.sha256
                        or rule.missing(state,self.limits.min_confidence,action=action)
                        or not activation_parent_valid({**active,"steps":steps[:1]},hand_goal,frame,vision.sha256,
                            logical_action=rule.logical_action)):
                    raise ValueError("自己chain Cancelの実親ACTIVATE/現在permissionが不足")
                evidence=state.facts.get("hand_search.own_chain_caption")
                try:raw=json.loads(evidence.value) if evidence is not None else {}
                except (TypeError,ValueError):raw={}
                if (evidence is None or evidence.observed_at!=frame.captured_at
                        or raw.get("config_sha256")!=caption.sha256 or raw.get("score",0)<.85
                        or raw.get("click_point")!=[545,681]):
                    raise ValueError("自己chain Cancelの現在caption/hash/点が不足")
                return self.screen_rect[0]+545,self.screen_rect[1]+681
            if hand_goal is not None and action.source_region in {hand_goal.activate_region,hand_goal.inspect_region}:
                proof=action.hand_search_proof;vision=self.pipeline.perception.hand_vision
                if (proof is None or proof.profile_sha256!=vision.sha256 or proof.frame_seq!=frame.sequence
                        or proof.observed_at!=frame.captured_at or proof.client_rect!=tuple(self.screen_rect)
                        or proof.action_type!=action.type.value or action.card_id!="13906"
                        or proof.layout_id not in vision.config["layouts"]):
                    raise ValueError("hand-search同frame/profile/source座標証拠が不足")
                x,y,w,h=proof.evidence_bbox;px,py=proof.point
                if not (0<=x<x+w<=1280 and 0<=y<y+h<=720 and x<=px<x+w and y<=py<y+h):
                    raise ValueError("hand-search点が実bbox/client外")
                if action.type.value=="ACTIVATE":
                    cfg=vision.config["layouts"][proof.layout_id]
                    if list(proof.evidence_bbox)!=cfg["effect_box"] or list(proof.point)!=cfg["effect_point"]:
                        raise ValueError("hand source/effect点不一致")
                else:
                    ep=vision.episode
                    if not ep or not ep.get("handoff") or ep.get("failed") or not ep.get("ready"):
                        raise ValueError("実incoming handoffなし")
                    active=self.telemetry.active;steps=(active or {}).get("steps",[])
                    if (not active or active.get("action_id")!=ep.get("action_id")
                            or active.get("hand_search_confirmation")!=hand_goal.model_dump(mode="json")
                            or len(steps)!=3 or any(s.get("input_sent") is not True or s.get("input_epoch_verified") is not True
                                or s.get("result")!="changed" for s in steps[:2])
                            or [s.get("action",{}).get("type") for s in steps[:2]]!=["ACTIVATE","CANCEL"]
                            or [s.get("action",{}).get("source_region") for s in steps[:2]]!=[hand_goal.activate_region,hand_goal.cancel_region]
                            or steps[1].get("input_epoch")!=frame.input_epoch):
                        raise ValueError("received hand親/Cancel実receiptが不足")
                    visible=ep.get("current_ready_geometry")
                    if (not visible or visible.get("role")!="handoff_visible_interior"
                            or list(proof.evidence_bbox)!=visible["bbox"] or list(proof.point)!=visible["point"]
                            or ep.get("last_seq")!=frame.sequence or ep.get("last_at")!=frame.captured_at):
                        raise ValueError("received hand可視安全点/現在frame不一致")
                    hx,hy,hw,hh=ep["handoff"]["bbox"]
                    if abs(px-(hx+hw/2))>2 or not hy<=py<=min(720,hy+hh):raise ValueError("received hand target不一致")
                return self.screen_rect[0]+px,self.screen_rect[1]+py
        h, w = image_shape[:2]
        view = self.calibration.viewport
        x = (view.x + region.rect.x * view.width + region.rect.width * view.width / 2) * w
        y = (view.y + region.rect.y * view.height + region.rect.height * view.height / 2) * h
        return self.screen_rect[0] + round(x), self.screen_rect[1] + round(y)

    def _save_frame(self, frame: Frame, name: str) -> str:
        with self.telemetry.span("artifact_write"):
            path = self.output / "screenshots" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if not write_image(path, frame.pixels):
                raise OSError(f"スクリーンショットを書き込めません: {path}")
        return str(path)

    def _record(self, log, entry):
        self.telemetry.event(entry.get("status", "step"), reason=entry.get("reason"))
        with self.telemetry.span("log_write"):
            log.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n")
            log.flush()

    def _save_verification_failure(self, latest_frame, latest_state, previous_recognized, reason, *, previous_hand_frame=None, endpoint=False):
        """新profile失敗時だけ実取得画像を保全。保存後の別取得を当時へ代用しません。"""
        planner = getattr(self.pipeline, "planner", None)
        action=getattr(self,"current_action",None)
        rule = planner.rule_for(action) if action is not None and hasattr(planner, "rule_for") else None
        snapshots = [("run_endpoint" if endpoint else "last_captured", latest_frame, latest_state)]
        if previous_recognized and latest_state is None:
            snapshots.append(("run_last_recognized" if endpoint else "last_recognized", *previous_recognized))
        if previous_hand_frame and previous_hand_frame[0].sequence!=latest_frame.sequence:
            snapshots.append(("before_hand_failure",*previous_hand_frame))
        for role, frame, state in snapshots:
            if frame is None:
                continue
            with self.telemetry.span("failure_diagnostic"):
                prefix = f"verify-failure-{self.completed:04d}-{role}-seq{frame.sequence}"
                path = Path(self._save_frame(frame, prefix + ".png"))
                scores = {}
                perception = self.pipeline.perception
                if isinstance(perception, Perception):
                    crops = self.calibration.crop_regions(frame.pixels)
                    scores = {name: {"raw_scores": matcher.diagnostic_scores(crops[name]),
                                     "threshold": matcher.region.threshold, "margin": matcher.region.margin}
                              for name, matcher in perception.matchers.items()}
                expected = getattr(rule, "expected_facts", {})
                report = {"schema": "actual-verification-failure-v1", "role": role, "reason": reason,
                    "telemetry_mode": self.telemetry.mode,
                    "capture_source": frame.capture_source, "capture_rect": frame.capture_rect,
                    "sequence": frame.sequence, "captured_at_monotonic": frame.captured_at,
                    "capture_start_perf": frame.capture_start, "capture_end_perf": frame.capture_end,
                    "input_epoch": frame.input_epoch, "image": str(path),
                    "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "state": state.model_dump(mode="json") if state is not None else None,
                    "state_unavailable_reason": "recognition_not_completed" if state is None else None,
                    "expected_facts": expected, "expected_prompts": getattr(rule, "expected_prompts", []),
                    "observed_expected_facts": {key: state.facts[key].model_dump(mode="json")
                        if state is not None and key in state.facts else None for key in expected},
                    "configured_roi_diagnostic_scores": scores,
                    "hand_episode":(self.telemetry.active or {}).get("hand_episode"),
                    "notice": "rawscoreは失敗保存時の診断再計算。実取得clockを保持しfresh化しません。相対手札ROIとは別です"}
                save_json(path.with_suffix(".json"), report)
                self.telemetry.event("verification_failure_snapshot", image=str(path),
                    sidecar=str(path.with_suffix(".json")), frame_seq=frame.sequence, role=role)

    def _response_verification_scope(self):
        """現在actionの宣言goalとactiveledger一致時だけ認識省略を許可します。"""
        from .strategy_rules import LogicalResponseDecline
        action = getattr(self,"current_action",None)
        planner = getattr(self.pipeline,"planner",None)
        rule = planner.rule_for(action) if action is not None and hasattr(planner,"rule_for") else None
        goal = getattr(rule,"logical_response_decline",None)
        active = self.telemetry.active
        if (isinstance(goal,LogicalResponseDecline) and active is not None
                and active.get("response_decline") == self.telemetry.response_spec(rule)):
            return goal
        return None

    def _verify(self, before: Frame, initial_state: GameState) -> tuple[Frame | None, GameState | None, str]:
        deadline = self.clock() + self.limits.verify_seconds
        if self.deadline is not None:
            deadline = min(deadline, self.deadline)
        unexpected = None
        latest_frame = latest_state = previous_recognized = None
        while self.clock() < deadline:
            with self.telemetry.span("frontmost_stop_check"):
                if self.stop_signal.stopped():
                    return None, None, "esc"
                if hasattr(self.stop_signal, "ready") and not self.stop_signal.ready():
                    return None, None, "input_blocked"
            with self.telemetry.span("poll_wait"):
                self.sleep(self.limits.verify_poll_seconds)
            with self.telemetry.span("frontmost_stop_check"):
                if self.stop_signal.stopped():
                    return None, None, "esc"
            try:
                after = self.capture.read()
            except InputBlocked as exc:
                self.telemetry.event("capture_activity_blocked", failure_category="State failure", reason=str(exc))
                return None, None, "input_blocked"
            if after is None:
                continue
            latest_frame, latest_state = after, None
            self._remember_runtime(after)
            with self.telemetry.span("verify_input_control"):
                if self.guarded_scope:
                    if (self.current_input_epoch is None or after.input_epoch != self.current_input_epoch
                            or after.capture_source != "live_mss" or after.capture_rect != tuple(self.screen_rect)):
                        self.telemetry.event("verify_input_activity_changed", failure_category="State failure")
                        return after, None, "input_blocked"
                    self.telemetry.current_step["input_epoch_verified"] = True
            try:
                recognition_start = self.telemetry.clock()
                hand_rule=None
                if isinstance(self.pipeline.perception, Perception):
                    scope = self._response_verification_scope()
                    hand_rule=getattr(getattr(self.pipeline,"planner",None),"rule_for",lambda a:None)(self.current_action)
                    hand_spec=self.telemetry.hand_spec(hand_rule)
                    hand_context=self.telemetry.active if hand_spec is not None and self.telemetry.active is not None and self.telemetry.active.get("hand_search_confirmation")==hand_spec else None
                    if hand_context is not None:
                        state=self.pipeline.perception.process(after,deadline=deadline,hand_episode_context=hand_context)
                        episode=getattr(self.pipeline.perception,"hand_episode",None)
                        if episode is not None:self.telemetry.active["hand_episode"]=json.loads(json.dumps(episode))
                    elif scope is not None:
                        state = self.pipeline.perception.process(after, deadline=deadline,verification_scope=scope)
                    else:
                        state = self.pipeline.perception.process(after, deadline=deadline)
                else:
                    state = self.pipeline.perception.process(after)
                latest_state = state
                self._remember_runtime(after,state)
                prior_hand_frame=previous_recognized
                previous_recognized = (after, state)
                spans = getattr(self.pipeline.perception, "stage_spans", None)
                self.telemetry.import_spans(spans or [{"stage": "recognition", "start": recognition_start, "end": self.telemetry.clock()}])
            except TimeoutError:
                self.telemetry.import_spans([{"stage": "recognition", "start": recognition_start, "end": self.telemetry.clock(), "error": "TimeoutError"}])
                self.telemetry.event("recognition_timeout", failure_category="Recognition failure")
                break
            except Exception:
                self.telemetry.import_spans([{"stage": "recognition", "start": recognition_start, "end": self.telemetry.clock(), "error": "RecognitionError"}])
                raise
            episode=(self.telemetry.active or {}).get("hand_episode")
            if episode and episode.get("failed") and self.telemetry.hand_spec(hand_rule) is not None:
                reason=episode["failed"]
                category={"receipt_capture_scope_mismatch":"State failure","expired_or_repeated_frame":"State failure",
                    "expired_handoff":"Verification failure"}.get(reason,"Recognition failure")
                self.telemetry.event("hand_episode_failed",failure_category=category,reason=reason,
                    frame_seq=after.sequence,captured_at_monotonic=after.captured_at)
                self._save_verification_failure(after,state,None,"hand_episode_failed:"+reason,previous_hand_frame=prior_hand_frame)
                return after,state,"unchanged"
            if state.terminal.value is True and state.terminal.confidence >= self.limits.min_confidence:
                return after, state, "duel_ended"
            with self.telemetry.span("verify_input_control"):
                if self.guarded_scope:
                    if not 0 <= self.clock() - after.captured_at <= self.limits.max_observation_age:
                        self.telemetry.event("verify_capture_stale", failure_category="Verification failure")
                        return after, state, "input_blocked"
                    try:
                        if self.clicker.input_epoch() != self.current_input_epoch:
                            self.telemetry.event("post_recognition_input_activity_changed", failure_category="State failure")
                            return after, state, "input_blocked"
                    except InputBlocked as exc:
                        self.telemetry.event("post_recognition_activity_unavailable", failure_category="State failure", reason=str(exc))
                        return after, state, "input_blocked"
            with self.telemetry.span("predicate"):
                planner = getattr(self.pipeline, "planner", None)
                rule = planner.rule_for(self.current_action) if hasattr(planner, "rule_for") else None
                hand_rule=getattr(rule,"logical_hand_search_confirmation",None) is not None
                if hand_rule and not self.telemetry.hand_step_confirmed(rule,state):continue
                logical_result = (getattr(rule, "logical_end", False) and self.telemetry.active is not None
                                  and self.telemetry.goal_confirmed(rule, state)
                                  and self.verification.changed(before.pixels, after.pixels))
                if hand_rule:logical_result=self.verification.changed(before.pixels,after.pixels)
                if getattr(rule, "logical_response_decline", None) is not None and not logical_result:
                    # 意味別辞退は実入力と陽性outcomeのANDだけで確認します。
                    # 不成立時はpendingを保ち、全画面差分fallbackへ進みません。
                    continue
                if state.sequence != initial_state.sequence and (logical_result or self.verification.expected(
                        before.pixels, after.pixels, initial_state, state, self.current_action)):
                    if planner and not planner.expected(self.current_action, state):
                        unexpected = (after, state)
                        continue
                    if getattr(rule, "logical_end", False) and self.telemetry.active is not None:
                        if not self.telemetry.goal_confirmed(rule, state):
                            unexpected = (after, state)
                            continue
                    return after, state, "changed"
        if unexpected:
            if self.guarded_scope:
                self._save_verification_failure(latest_frame, latest_state, previous_recognized, "unexpected_state")
            return *unexpected, "unexpected_state"
        if self.guarded_scope:
            self._save_verification_failure(latest_frame, latest_state, previous_recognized, "verify_timeout")
            return latest_frame, latest_state, "unchanged"
        return None, None, "unchanged"

    def run(self) -> dict:
        self.output.mkdir(parents=True, exist_ok=True)
        started = self.clock()
        self.deadline = started + self.limits.max_seconds
        status = "running"
        log_path = self.output / "actions.jsonl"
        blocked = False
        try:
            with log_path.open("a", encoding="utf-8") as log:
                while status == "running":
                    if self.stop_signal.stopped():
                        status = "esc"
                        break
                    if self.clock() - started >= self.limits.max_seconds:
                        status = "time_limit"
                        break
                    if self.completed >= self.limits.max_actions:
                        status = "action_limit"
                        break
                    if hasattr(self.stop_signal, "ready") and not self.stop_signal.ready():
                        self.control_state = self.stop_signal.state
                        if not blocked:
                            self._record(log, {"at": self.clock(), "status": "input_blocked", "control": self.control_state})
                        blocked = True
                        self.pending_frame = None
                        self.pending_state = None
                        self.decision_frame = self.decision_state = None
                        self.decision_capture_start = None
                        self.telemetry.finish("interrupted", "Input failure", "input_blocked")
                        if isinstance(self.pipeline, Pipeline):
                            self.pipeline.decision_started = None
                            if self.pipeline.strategy_fallback:
                                self.pipeline.strategy_fallback.discard()
                        self.sleep(self.limits.verify_poll_seconds)
                        continue
                    if blocked:
                        # 再開時には以前の画面・プランをそのまま実行しません。
                        self.gate.previous = None
                        if getattr(self.pipeline, "planner", None):
                            self.pipeline.planner.reset()
                        blocked = False
                    self.control_state = ControlState.OBSERVING
                    before = self.pending_frame
                    observed_state = self.pending_state
                    decision_due = bool(getattr(self.pipeline, "decision_due", False))
                    if decision_due and self.decision_frame is not None:
                        before, observed_state = self.decision_frame, self.decision_state
                    self.pending_frame = None
                    self.pending_state = None
                    capture_read_ms = 0.0
                    if before is None or self.clock() - before.captured_at > self.limits.max_observation_age:
                        capture_started = time.perf_counter()
                        try:
                            before = self.recovery.next_frame(self.capture)
                        except InputBlocked as exc:
                            if not self.guarded_scope:
                                raise
                            status = "input_blocked"
                            self.telemetry.event("capture_input_guard_unavailable", reason=str(exc), failure_category="State failure")
                            break
                        observed_state = None
                        capture_read_ms = (time.perf_counter()-capture_started)*1000
                    if before is None:
                        self.sleep(self.limits.verify_poll_seconds)
                        continue
                    self._remember_runtime(before,observed_state)
                    # 非同期判断の完了も処理の契機にし、静止画面の更新期限を待ちません。
                    strategy = getattr(self.pipeline, "strategy_fallback", None)
                    future = getattr(strategy, "future", None)
                    decision_ready = future is not None and future.done()
                    if not self.gate.accept(before) and not decision_ready and not decision_due:
                        self.sleep(self.limits.verify_poll_seconds)
                        continue
                    if self.decision_capture_start is None:
                        self.decision_capture_start = before.capture_start
                    if observed_state is not None and isinstance(self.pipeline, Pipeline):
                        result = self.pipeline.process(before, capture_read_ms=capture_read_ms,
                                                       observed_state=observed_state)
                    else:
                        result = self.pipeline.process(before, capture_read_ms=capture_read_ms)
                    self.telemetry.import_spans(result.get("stage_spans", []))
                    if result.get("error"):
                        self.telemetry.event("recognition_error", failure_category="Recognition failure", reason=result["error"])
                    state = GameState.model_validate(result["state"])
                    self._remember_runtime(before,state)
                    self.telemetry.observe(before, state)
                    self.decision_frame, self.decision_state = before, state
                    if state.terminal.value is True and state.terminal.confidence >= self.limits.min_confidence:
                        status = "duel_ended"
                        break
                    rec = result["recommendation"]
                    action_data = rec.get("action")
                    if rec.get("recognition_status", "").startswith("llm"):
                        self.telemetry.event("fallback")
                    elif not action_data:
                        self.decision_capture_start = None
                    if not action_data or rec.get("confidence", 0) < self.limits.min_confidence:
                        self._record(log, {"at": self.clock(), "status": "abstain", "reason": rec.get("reason"), "confidence": rec.get("confidence", 0)})
                        self.sleep(self.limits.verify_poll_seconds)
                        continue
                    action = Action.model_validate(action_data)
                    if action.confidence < self.limits.min_confidence or action.observed_at != before.captured_at:
                        self._record(log, {"at": self.clock(), "status": "abstain", "reason": "信頼度不足または候補が古い"})
                        continue
                    rule = self.pipeline.planner.rule_for(action) if hasattr(getattr(self.pipeline, "planner", None), "rule_for") else None
                    self.telemetry.begin_step(action, rule, state, before, rec, self.decision_capture_start)
                    self.decision_capture_start = None
                    with self.telemetry.span("coordinate"):
                        x, y = self._coordinates(action, before.pixels.shape, frame=before, state=state)
                    self.current_action = action
                    fingerprint = hashlib.sha256(f"{action.type}:{x}:{y}".encode()).hexdigest()
                    if fingerprint == self.repeat_key:
                        self.repeat_count += 1
                    else:
                        self.repeat_key, self.repeat_count = fingerprint, 1
                    if self.repeat_count > self.limits.max_same_action:
                        status = "repeated_action"
                        self._record(log, {"at": self.clock(), "status": status, "action": action.model_dump(mode="json")})
                        break
                    self.sleep(self.limits.settle_seconds)
                    if self.stop_signal.stopped():
                        status = "esc"
                        break
                    if self.clock() >= self.deadline:
                        status = "time_limit"
                        break
                    if self.limits.settle_seconds:
                        # 待機中にダイアログや配置が変わり得るため再観測します。
                        capture_started = time.perf_counter()
                        fresh = self.capture.read()
                        capture_read_ms = (time.perf_counter()-capture_started)*1000
                        if fresh is None:
                            continue
                        self._remember_runtime(fresh)
                        fresh_result = self.pipeline.process(fresh, capture_read_ms=capture_read_ms)
                        self.telemetry.import_spans(fresh_result.get("stage_spans", []))
                        fresh_state = GameState.model_validate(fresh_result["state"])
                        self._remember_runtime(fresh,fresh_state)
                        if fresh_state.terminal.value is True and fresh_state.terminal.confidence >= self.limits.min_confidence:
                            status = "duel_ended"
                            break
                        fresh_rec = fresh_result["recommendation"]
                        candidates = ([Action.model_validate(fresh_rec["action"])]
                                      if fresh_rec.get("action") and fresh_rec.get("confidence", 0) >= self.limits.min_confidence
                                      else [])
                        matches = [a for a in candidates if (a.type, a.source_region, a.card_id, a.target)
                                   == (action.type, action.source_region, action.card_id, action.target)
                                   and a.confidence >= self.limits.min_confidence]
                        if len(matches) != 1:
                            self.pending_frame = fresh
                            continue
                        before, state, action = fresh, fresh_state, matches[0]
                        result = fresh_result
                        self.current_action = action
                        with self.telemetry.span("coordinate"):
                            x, y = self._coordinates(action, before.pixels.shape, frame=before, state=state)
                    if not 0 <= self.clock() - before.captured_at <= self.limits.max_observation_age:
                        continue
                    self._save_frame(before, f"before-{self.completed:04d}.png")
                    if self.stop_signal.stopped() or self.clock() >= self.deadline:
                        status = "esc" if self.stop_signal.stopped() else "time_limit"
                        break
                    if self.clock() - before.captured_at > self.limits.max_observation_age:
                        continue
                    action_started = self.clock()
                    input_started = time.perf_counter()
                    self.gate.previous = None
                    if hasattr(self.pipeline, "action_issued"):
                        self.pipeline.action_issued(action)
                    try:
                        with self.telemetry.span("input"):
                            with self.telemetry.span("pre_input_control"):
                                self.telemetry.assert_data_unchanged()
                                if self.guarded_scope:
                                    if (not self.inspection_live_bound or before.input_epoch is None
                                            or self.clicker.input_epoch() != before.input_epoch
                                            or (self.current_input_epoch is not None and before.input_epoch != self.current_input_epoch)):
                                        raise InputBlocked("取得後に入力活動が変化しました")
                            self.clicker.click(x, y)
                        self.telemetry.input_result(True, (x, y))
                    except InputBlocked as exc:
                        self.telemetry.input_result(False, (x, y))
                        self.telemetry.complete_step("input_blocked", rule, None)
                        if hasattr(self.pipeline, "action_feedback"):
                            self.pipeline.action_feedback("input_blocked")
                        self._record(log, {"at": self.clock(), "status": "input_blocked", "reason": str(exc)})
                        blocked = True
                        if self.guarded_scope:
                            status = "input_blocked"
                            break
                        self.sleep(self.limits.verify_poll_seconds)
                        continue
                    except Exception as exc:
                        self.telemetry.input_result(None, (x, y))
                        self.telemetry.complete_step("input_error_outcome_unknown", rule, None)
                        if hasattr(self.pipeline, "action_feedback"):
                            self.pipeline.action_feedback("input_error_outcome_unknown")
                        self.completed += 1
                        self._record(log, {"index": self.completed, "at": action_started,
                                           "status": "input_error_outcome_unknown", "error": str(exc),
                                           "action": action.model_dump(mode="json"), "screen_point": [x,y]})
                        if self.guarded_scope:
                            status = "input_error_outcome_unknown"
                            break
                        continue
                    if self.guarded_scope:
                        try:
                            with self.telemetry.span("post_input_control"):
                                self.current_input_epoch = self.clicker.input_epoch()
                                self.telemetry.current_step.update(input_epoch=self.current_input_epoch,
                                    input_epoch_verified=False, input_epoch_clock="opaque_GetLastInputInfo_session_token")
                        except InputBlocked as exc:
                            self.current_input_epoch = None
                            self.telemetry.event("post_input_activity_unavailable", failure_category="State failure", reason=str(exc))
                    action_ms = (time.perf_counter() - input_started) * 1000
                    self.control_state = ControlState.VERIFYING
                    verify_started = time.perf_counter()
                    with self.telemetry.span("verify") as verification_span:
                        after, new_state, verification = self._verify(before, state)
                    self.telemetry.complete_step(verification, rule, new_state, at=verification_span["end"])
                    verification_ms = (time.perf_counter() - verify_started) * 1000
                    if hasattr(self.pipeline, "action_feedback"):
                        self.pipeline.action_feedback(verification)
                    self.pending_frame = after
                    self.pending_state = new_state
                    latency = (action_started - before.captured_at) * 1000
                    self.latencies.append(latency)
                    self.completed += 1
                    entry = {"index": self.completed, "at": action_started, "status": verification,
                             "action": action.model_dump(mode="json"), "screen_point": [x,y],
                             "before": str(self.output / "screenshots" / f"before-{self.completed-1:04d}.png"),
                             "after": self._save_frame(after, f"after-{self.completed:04d}.png") if after is not None else None,
                             "before_sequence": state.sequence, "after_sequence": new_state.sequence if new_state else None,
                             "retries": self.repeat_count - 1,
                             "observation_to_click_ms": latency,
                             "state_before": state.model_dump(mode="json"),
                             "state_after": new_state.model_dump(mode="json") if new_state else None,
                             "metrics": {**result.get("metrics", {}), "action_ms": action_ms,
                                         "verification_ms": verification_ms,
                                         "operation_ms": (time.perf_counter() - input_started)*1000},
                             "plan": self.pipeline.planner.snapshot() if getattr(self.pipeline, "planner", None) else None}
                    self._record(log, entry)
                    if self.guarded_scope and verification != "changed":
                        status = "verification_failed" if verification in {"unchanged", "unexpected_state"} else verification
                        break
                    if verification == "esc":
                        status = "esc"
                    elif verification == "duel_ended":
                        status = "duel_ended"
                    elif verification == "unchanged":
                        # 次周回は必ず新しい画面から認識し、古いクリック点を使わない。
                        if self.repeat_count > self.limits.max_retries:
                            status = "verification_failed"
                    elif verification == "input_blocked":
                        blocked = True
                    elif verification == "unexpected_state":
                        status = "unexpected_state"
                    else:
                        self.repeat_count = 0
        except Exception as exc:
            self.telemetry.event("loop_error", error=type(exc).__name__, reason=str(exc))
            status = "loop_error"
            raise
        finally:
            try:
                if status=="time_limit" and self.guarded_scope and self.last_runtime_frame is not None:
                    self._save_verification_failure(self.last_runtime_frame,self.last_runtime_state,
                        self.last_runtime_recognized,"time_limit",endpoint=True)
            finally:
                self.telemetry.close(status)
                self.capture.close()
                self.control_state = ControlState.STOPPED
        summary = {"status": status, "actions": self.completed, "elapsed_seconds": self.clock() - started,
                   "action_log": str(log_path), "screenshots": str(self.output / "screenshots"),
                   "logical_actions": len(self.telemetry.records), "logical_action_log": str(self.output / "logical-actions.jsonl"),
                   "telemetry_mode": self.telemetry.mode,
                   "observation_to_click_ms_p95": float(np.percentile(self.latencies, 95)) if self.latencies else None}
        save_json(self.output / "agent-run.json", summary)
        return summary


def make_live_loop(pipeline, rect, output, fps, limits, window_title="masterduel", benchmark_trials=None,
                   run_purpose="pilot", cohort_manifest=None, cohort_slot=None, execution_conditions=None):
    desktop = WindowsDesktop()
    control = DesktopControl(desktop, desktop.find(window_title), rect)
    capture = LiveCaptureSource("mss", rect, fps)
    return AgentLoop(capture, pipeline, pipeline.perception.calibration, GuardedClicker(control),
                     control, output, rect, limits, telemetry_mode="live_autonomous", benchmark_trials=benchmark_trials,
                     run_purpose=run_purpose, cohort_manifest=cohort_manifest, cohort_slot=cohort_slot,
                     execution_conditions={"fps": fps, "window_title": window_title, "backend": "mss",
                                           "runtime": execution_conditions})
