"""公開情報と校正済み候補を使う、確認付きの展開手順。"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from .models import Action, ActionType, GameState, Model, Phase, Player, Recommendation


class CardRequirement(Model):
    side: Player = Player.SELF
    zone_prefix: str
    card_id: str

    def matches(self, state: GameState, confidence: float) -> bool:
        player = state.self if self.side == Player.SELF else state.opponent
        return any(name.startswith(self.zone_prefix) and obs.value is not None
                   and obs.value.card_id == self.card_id and obs.confidence >= confidence
                   and obs.observed_at == state.captured_at
                   for name, obs in player.zones.items())


class PlanStep(Model):
    description: str
    type: ActionType
    source_region: str = Field(pattern=r"^action\.")
    card_id: str | None = None
    target: str | None = None
    phases: list[Phase] = Field(default_factory=lambda: [Phase.MAIN1, Phase.MAIN2])
    requires: list[CardRequirement] = Field(default_factory=list)
    expected_cards: list[CardRequirement] = Field(default_factory=list)
    expected_prompt: str | None = None
    expected_phase: Phase | None = None

    def expected(self, state: GameState, confidence: float) -> bool:
        if self.expected_prompt is not None and not (
            state.prompt.value == self.expected_prompt and state.prompt.confidence >= confidence
            and state.prompt.observed_at == state.captured_at):
            return False
        if self.expected_phase is not None and not (
            state.phase.value == self.expected_phase and state.phase.confidence >= confidence
            and state.phase.observed_at == state.captured_at):
            return False
        return all(req.matches(state, confidence) for req in self.expected_cards)

    def matches(self, action: Action) -> bool:
        return (action.type == self.type and action.source_region == self.source_region
                and (self.card_id is None or action.card_id == self.card_id)
                and (self.target is None or action.target == self.target))


class Recipe(Model):
    id: str = Field(min_length=1)
    goal: str
    priority: int = 0
    requires: list[CardRequirement] = Field(min_length=1)
    steps: list[PlanStep] = Field(min_length=1)


class PlanBook(Model):
    recipes: list[Recipe]
    min_confidence: float = Field(default=.98, gt=0, le=1)

    @classmethod
    def load(cls, path: Path) -> PlanBook:
        book = cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if len({r.id for r in book.recipes}) != len(book.recipes):
            raise ValueError("展開手順の id が重複しています")
        return book


class TurnPlanner:
    """相手ターンでも準備し、実行結果が確認された時だけ次の UI 手順へ進みます。"""

    def __init__(self, book: PlanBook):
        self.book = book
        self.recipe: Recipe | None = None
        self.index = 0
        self.pending: Action | None = None
        self.turn_key = None
        self.opponent_key = None
        self.finished: set[str] = set()
        self.reason = "手札と盤面の認識を待っています"

    def reset(self):
        self.recipe, self.index, self.pending = None, 0, None
        self.turn_key = self.opponent_key = None
        self.finished.clear()

    def observe(self, state: GameState):
        if state.terminal.value is True:
            self.reset()
            return
        # 未知の盤面を前回の既知情報で補完しません。
        turn = (state.turn.value, state.turn_player.value)
        opponent = tuple(sorted((name, obs.value.card_id if obs.value else None)
                                for name, obs in state.opponent.zones.items()))
        if self.turn_key is not None and turn != self.turn_key:
            self.recipe, self.index, self.pending = None, 0, None
            self.finished.clear()
        elif self.opponent_key is not None and opponent != self.opponent_key:
            # 公開盤面が変わったら、残った手札から再検討します。
            self.recipe, self.index, self.pending = None, 0, None
            self.reason = "相手の公開盤面が変化したため再検討しました"
        self.turn_key, self.opponent_key = turn, opponent
        if self.recipe is None:
            choices = [r for r in self.book.recipes if r.id not in self.finished
                       and all(req.matches(state, self.book.min_confidence) for req in r.requires)]
            if choices:
                self.recipe = sorted(choices, key=lambda r: (-r.priority, r.id))[0]
                self.index = 0
                self.reason = "公開された手札・盤面からターンの方針を準備しました"

    def snapshot(self) -> dict:
        return {"recipe": self.recipe.id if self.recipe else None,
                "goal": self.recipe.goal if self.recipe else None,
                "step": self.index, "pending": self.pending is not None,
                "reason": self.reason}

    def expected(self, action: Action, state: GameState) -> bool:
        if self.recipe and self.pending and self.recipe.steps[self.index].matches(action):
            return self.recipe.steps[self.index].expected(state, self.book.min_confidence)
        return True

    def decide(self, state: GameState, actions: tuple[Action, ...]) -> Recommendation:
        def wait(reason):
            return Recommendation(reason=reason, recognition_status="abstained")
        if self.recipe is None:
            return wait("登録済みの展開条件に一致しません。追加判断が必要です")
        if self.pending:
            return wait("直前の操作結果を確認しています")
        step = self.recipe.steps[self.index]
        if state.turn_player.value != Player.SELF or state.phase.value not in step.phases:
            return wait(f"方針「{self.recipe.goal}」を準備済み。対応フェイズを待っています")
        if not all(req.matches(state, self.book.min_confidence) for req in step.requires):
            return wait("次の手順の盤面条件を確認できません。追加判断が必要です")
        matches = [a for a in actions if step.matches(a) and a.confidence >= self.book.min_confidence]
        if len(matches) != 1:
            return wait("次の手順の表示候補を一意に確認できません。画面変化を待っています")
        action = matches[0]
        return Recommendation(action=action, target=action.target,
                              confidence=min(action.confidence, state.phase.confidence,
                                             state.turn_player.confidence),
                              reason=f"方針: {self.recipe.goal}。手順: {step.description}",
                              recognition_status="planned")

    def issued(self, action: Action):
        if self.recipe and self.recipe.steps[self.index].matches(action):
            self.pending = action

    def feedback(self, status: str):
        if self.pending is None:
            return
        self.pending = None
        if status == "changed":
            self.index += 1
            if self.recipe and self.index == len(self.recipe.steps):
                self.finished.add(self.recipe.id)
                self.recipe, self.index = None, 0
            self.reason = "表示 UI の遷移を確認しました。効果の解決は次の盤面条件で確認します"
        elif status == "duel_ended":
            self.reset()
        elif status == "unexpected_state":
            if self.recipe:
                self.finished.add(self.recipe.id)
            self.recipe, self.index = None, 0
            self.reason = "期待状態と異なるためコンボを中断しました"
        else:
            self.reason = "操作結果を確認できないため、同じ手順を最新画面で再検討します"
