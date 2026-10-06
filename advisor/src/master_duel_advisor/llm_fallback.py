"""任意プロバイダー向けの構造化・非同期戦略判断境界。画像は渡しません。"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import time
from typing import Literal

from pydantic import Field

from .models import ActionType, GameState, Model, Recommendation


class StrategyChoice(Model):
    type: ActionType
    source_region: str
    card_id: str | None
    target: str | None
    confidence: float = Field(ge=0, le=1)
    reason: str


def semantic_key(state: GameState):
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k,v in value.items() if k not in {
                "sequence", "captured_at", "observed_at", "media_time", "confidence", "source"}}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    payload = clean(state.model_dump(mode="json"))
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


class StrategyFallback:
    """プロバイダー自体にネットワークtimeoutが必要です。通常ループを待たせません。"""
    def __init__(self, provider, max_calls=5, timeout=5, cooldown=10, min_confidence=.98,
                 clock=time.monotonic):
        if (max_calls < 1 or not math.isfinite(timeout) or not 0 < timeout <= 10
                or not math.isfinite(cooldown) or cooldown < 0 or not 0 < min_confidence <= 1):
            raise ValueError("例外判断の予算・待機時間・信頼度が不正です")
        self.provider, self.clock = provider, clock
        self.max_calls, self.timeout, self.cooldown = max_calls, timeout, cooldown
        self.min_confidence = min_confidence
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="strategy-fallback")
        self.future = None
        self.key = None
        self.started = self.last_started = float("-inf")
        self.calls = 0
        self.last_error = None
        self.last_latency_ms = None
        self.deadline = None
        self.last_status = "idle"

    def discard(self):
        """実行中の通信は増やさず、遅れて返った結果を永久に無効化します。"""
        self.key = None
        if self.future is not None and (self.future.done() or self.future.cancel()):
            self.future = None

    def _invoke(self, payload, schema):
        started = time.perf_counter()
        try:
            return self.provider(payload,schema)
        finally:
            self.last_latency_ms = (time.perf_counter()-started)*1000

    def request(self, state: GameState, reason: Literal["interruption", "combo_failed", "ambiguous_routes", "unfamiliar_board", "low_confidence"], *, deadline=None):
        if reason not in {"interruption", "combo_failed", "ambiguous_routes", "unfamiliar_board", "low_confidence"}:
            raise ValueError("例外的な戦略判断の理由が必要です")
        if self.future is not None and self.key is None and self.future.done():
            self.future = None
        if deadline is not None and self.clock() >= deadline:
            self.last_status = "timeout"
            return False
        if self.future is not None:
            self.last_status = "pending" if self.key is not None else "busy"
            return False
        if self.calls >= self.max_calls:
            self.last_status = "budget_exhausted"
            return False
        if self.clock()-self.last_started < self.cooldown:
            self.last_status = "cooldown"
            return False
        if not state.visible_actions or state.animation.value is True:
            self.last_status = "unavailable"
            return False
        self.key = semantic_key(state)
        self.started = self.last_started = self.clock()
        self.deadline = min(self.started + self.timeout, deadline) if deadline is not None else self.started + self.timeout
        self.last_status = "pending"
        self.last_error = None
        self.calls += 1
        self.future = self.executor.submit(self._invoke, state.model_dump(mode="json"), StrategyChoice.model_json_schema())
        return True

    def poll(self, state: GameState, legal_actions):
        if self.future is None:
            return None
        if self.key is None:
            self.discard()
            self.last_status = "discarded"
            return None
        if self.clock() >= self.deadline or semantic_key(state) != self.key:
            self.last_error = "応答期限超過または盤面が変化したため破棄"
            self.last_status = "timeout" if self.clock() >= self.deadline else "discarded"
            self.discard()
            return None
        if not self.future.done():
            return None
        future, self.future = self.future, None
        try:
            choice = StrategyChoice.model_validate(future.result())
        except Exception as exc:
            self.last_error = str(exc)
            self.last_status = "error"
            return None
        matches = [a for a in legal_actions if a.type == choice.type and a.source_region == choice.source_region
                   and a.card_id == choice.card_id and a.target == choice.target
                   and a.observed_at == state.captured_at and a.confidence >= self.min_confidence]
        if len(matches) != 1 or choice.confidence < self.min_confidence:
            self.last_error = "現在の校正済み候補と一致しないため破棄"
            self.last_status = "rejected"
            return None
        a = matches[0]
        self.last_error = None
        self.last_status = "ready"
        return Recommendation(action=a,target=a.target,confidence=min(choice.confidence,a.confidence),
                              reason=choice.reason,recognition_status="llm_strategy")

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
