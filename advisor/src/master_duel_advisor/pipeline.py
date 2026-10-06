from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np

from .capture import Frame
from .decision import DecisionContext, DecisionEngine
from .models import GameState, Recommendation
from .perception import Perception
from .rules import ActionGenerator
from .regions import Calibration
from .tracking import Tracker
from .planning import TurnPlanner
from .ui_policy import UiPolicy
from .llm_fallback import StrategyFallback


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
    def __init__(self, perception: Perception, rules: ActionGenerator | None = None,
                 planner: TurnPlanner | None = None, ui_policy: UiPolicy | None = None,
                 strategy_fallback=None, clock=time.monotonic):
        self.perception = perception
        self.rules = rules or ActionGenerator()
        self.tracker, self.engine = Tracker(), DecisionEngine()
        self.last: dict | None = None
        self.planner = planner
        self.ui_policy = ui_policy or UiPolicy()
        self.snapshot_sink = None
        self.strategy_fallback = strategy_fallback
        self.clock = clock
        self.decision_started = None
        self.decision_seconds = 10.0

    @property
    def decision_due(self):
        return self.decision_started is not None and self.clock() >= self.decision_started + self.decision_seconds

    def action_issued(self, action):
        self.decision_started = None
        if self.planner:
            self.planner.issued(action)

    def action_feedback(self, status):
        if self.planner:
            self.planner.feedback(status)

    def response_ui_required(self, state, actions):
        book = getattr(self.planner, "book", None)
        response_rules = [r for r in getattr(book, "rules", []) if getattr(r, "logical_response_decline", None)
                          or getattr(r,"logical_hand_search_confirmation",None)]
        return bool(response_rules and (str(state.prompt.value).startswith(("response.","hand.dragondark."))
                    or any(r.matches(a) for r in response_rules for a in actions)))

    def process(self, frame: Frame, capture_read_ms: float = 0, *,
                observed_state: GameState | None = None) -> dict:
        start = time.perf_counter()
        stage_start = time.perf_counter()
        stage_spans = []
        if self.decision_started is None:
            self.decision_started = self.clock()
        deadline = self.decision_started + self.decision_seconds
        error = None
        # 同じ取得画像の確認結果だけを再利用し、判断・手順は改めて更新します。
        if observed_state is not None and (observed_state.sequence != frame.sequence
                                          or observed_state.captured_at != frame.captured_at):
            raise ValueError("確認結果と取得画像が一致していません")
        try:
            if observed_state is not None:
                state = observed_state
            elif isinstance(self.perception, Perception):
                state = self.perception.process(frame, deadline=deadline)
            else:
                state = self.perception.process(frame)
        except (ValueError, TimeoutError) as exc:
            # 不正な表示範囲・配置では未知として扱い、前回の根拠を流用しません。
            state = GameState(sequence=frame.sequence, captured_at=frame.captured_at, media_time=frame.media_time)
            error = str(exc)
        perception_ms = 0 if observed_state is not None else (time.perf_counter()-start)*1000
        if observed_state is None:
            stage_spans.extend(getattr(self.perception, "stage_spans", []))
            if not stage_spans:
                stage_spans.append({"stage": "recognition", "start": stage_start, "end": time.perf_counter()})
        state_start = time.perf_counter()
        self.tracker.update(state)
        stage_spans.append({"stage": "state_build", "start": state_start, "end": time.perf_counter()})
        candidate_start = time.perf_counter()
        decision_start = time.perf_counter()
        actions = self.rules.generate(state, time.monotonic())
        ids = {obs.value.card_id for player in [state.self, state.opponent] for obs in player.zones.values() if obs.value is not None}
        cards = tuple(card for card_id in sorted(ids) if (card := self.perception.cards.get(card_id)) is not None)
        if self.planner:
            self.planner.observe(state)
        if getattr(self.planner, "strict", False):
            actions = self.planner.filter_actions(state, actions)
        stage_spans.append({"stage": "candidate", "start": candidate_start, "end": time.perf_counter()})
        selection_start = time.perf_counter()
        # デッキルール自身が正確なpromptと対象を検査するため、旧UI設定で遮断しません。
        response_ui = self.response_ui_required(state, actions)
        ui_recommendation = self.ui_policy.decide(state, tuple(actions)) if (
            response_ui or not getattr(self.planner, "strict", False)) else None
        if self.clock() >= deadline:
            recommendation = self._force_choice(state, actions)
        elif state.animation.value is True:
            recommendation = Recommendation(reason="演出終了を待っています", recognition_status="abstained")
        elif ui_recommendation is not None:
            recommendation = ui_recommendation
        elif self.planner:
            recommendation = self.planner.decide(state, tuple(actions))
            if recommendation.action is None and self.planner.recipe is None and not getattr(self.planner, "strict", False):
                recommendation = self.engine.decide(DecisionContext(state, tuple(self.tracker.events), cards, tuple(actions)))
        else:
            recommendation = self.engine.decide(DecisionContext(state, tuple(self.tracker.events), cards, tuple(actions)))
        # 未解決の確認UI・演出中・実行中コンボでは例外戦略に制御を渡しません。
        ambiguous = recommendation.recognition_status == "partial" and len(actions)>1
        if (not getattr(self.planner, "strict", False) and self.clock() < deadline and self.strategy_fallback and (recommendation.action is None or ambiguous)
                and state.prompt.value == "none" and state.animation.value is not True
                and not (self.planner and self.planner.pending)):
            choice = self.strategy_fallback.poll(state, tuple(actions))
            if choice:
                recommendation = choice
            else:
                reason = "ambiguous_routes" if ambiguous else "low_confidence"
                if isinstance(self.strategy_fallback, StrategyFallback):
                    # 期限切れの同じ判断をその場で再要求しません。
                    if self.strategy_fallback.last_status == "timeout":
                        recommendation = self._force_choice(state, actions)
                    else:
                        self.strategy_fallback.request(state, reason, deadline=deadline)
                        status = self.strategy_fallback.last_status
                        if status == "pending":
                            recommendation = Recommendation(reason="10秒を上限に戦略を判断しています", recognition_status="llm_pending")
                        else:
                            # 予算・クールダウンで待つより、現在の候補を決定的に選びます。
                            recommendation = self._force_choice(state, actions, trigger=status)
                else:
                    self.strategy_fallback.request(state, reason)
                    if ambiguous:
                        recommendation = Recommendation(reason="複数候補の例外戦略を非同期で確認しています", recognition_status="llm_pending")
        if self.clock() >= deadline:
            recommendation = self._force_choice(state, self.rules.generate(state, time.monotonic()))
        elapsed_ms = (self.clock() - self.decision_started) * 1000
        if recommendation.recognition_status != "llm_pending":
            self.decision_started = None
        decision_ms = (time.perf_counter()-decision_start)*1000
        self.last = {"state": state.model_dump(mode="json"), "events": [event.model_dump(mode="json") for event in self.tracker.events], "legal_actions": [a.model_dump(mode="json") for a in actions], "recommendation": recommendation.model_dump(mode="json"), "error": error, "metrics": {"capture_read_ms": capture_read_ms, "perception_ms": perception_ms, "decision_ms": decision_ms, "decision_elapsed_ms": elapsed_ms, "decision_limit_ms": 10000, "total_compute_ms": capture_read_ms+(time.perf_counter()-start)*1000, "api_calls": 0, "api_cost_usd": 0}}
        stage_spans.append({"stage": "decision", "start": selection_start, "end": time.perf_counter()})
        self.last["stage_spans"] = stage_spans
        self.last["plan"] = self.planner.snapshot() if self.planner else None
        if self.strategy_fallback:
            self.last["metrics"]["api_calls"] = self.strategy_fallback.calls
            self.last["metrics"]["api_cost_usd"] = None
            self.last["metrics"]["llm_ms"] = getattr(self.strategy_fallback,"last_latency_ms",None)
            self.last["llm_error"] = getattr(self.strategy_fallback,"last_error",None)
        self.last["planner_source"] = recommendation.recognition_status
        knowledge = getattr(self.perception.cards, "knowledge", None)
        if knowledge is not None:
            self.last["card_knowledge"] = {"pending": len(knowledge.pending),
                                            "ready": len(knowledge.ready),
                                            "last_error": knowledge.last_error}
        self.last["metrics"].update(cache_hits=0 if observed_state is not None else self.perception.cache_hits,
                                    recognized_regions=0 if observed_state is not None else self.perception.recognized_regions,
                                    ocr_ms=0 if observed_state is not None else getattr(self.perception, "ocr_ms", 0),
                                    state_build_ms=0 if observed_state is not None else getattr(self.perception, "state_build_ms", 0),
                                    perception_reused=observed_state is not None)
        if self.snapshot_sink:
            self.snapshot_sink(self.last)
        return self.last

    def _force_choice(self, state, actions, trigger="timeout"):
        """勝率モデルは未実装のため、現在の許容候補の認識信頼度で決着します。"""
        if isinstance(self.strategy_fallback, StrategyFallback):
            self.strategy_fallback.discard()
            self.strategy_fallback.last_status = "idle"
        if getattr(self.planner, "strict", False):
            actions = self.planner.filter_actions(state, actions)
        if self.response_ui_required(state, actions):
            # 期限切れでもstrictと意味別UiPolicyの二重ゲートを迂回しません。
            return self.ui_policy.decide(state, tuple(actions)) or Recommendation(
                reason="応答辞退の意味別UI規則がありません", recognition_status="abstained")
        candidates = [a for a in actions if a.confidence >= .98
                      and a.observed_at == state.captured_at
                      and 0 <= time.monotonic() - a.observed_at <= 1.0]
        if state.animation.value is True or state.terminal.value is True:
            candidates = []
        if not candidates:
            return Recommendation(reason=f"判断を終了しました（{trigger}）。新しい実行可能候補がありません",
                                  recognition_status="decision_no_candidate")
        action = sorted(candidates, key=lambda a: (-a.confidence, a.type.value, a.source_region))[0]
        return Recommendation(action=action, target=action.target, confidence=action.confidence,
                              reason=f"判断を終了しました（{trigger}）。現在の候補で認識信頼度が最高の行動を強制選択しました。勝率ではありません",
                              recognition_status="forced_choice")



def save_json(path: Path, value: object):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")
    temporary.replace(path)
