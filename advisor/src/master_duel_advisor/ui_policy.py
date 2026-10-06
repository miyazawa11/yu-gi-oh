"""promptの意味を設定したUIルールだけを優先実行します。"""
from pathlib import Path

from pydantic import Field

from .models import Action, ActionType, GameState, Model, Recommendation


class UiRule(Model):
    prompt: str = Field(min_length=1)
    type: ActionType
    source_region: str = Field(pattern=r"^action\.")
    card_id: str | None = None
    target: str | None = None


class UiPolicy(Model):
    rules: list[UiRule] = Field(default_factory=list)
    min_confidence: float = Field(default=.98, gt=0, le=1)

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def decide(self, state: GameState, actions: tuple[Action, ...]) -> Recommendation | None:
        if state.prompt.value in {None, "none"}:
            return None
        choices = [a for a in actions if any(
            r.prompt == state.prompt.value and r.type == a.type and r.source_region == a.source_region
            and (r.card_id is None or r.card_id == a.card_id)
            and (r.target is None or r.target == a.target) for r in self.rules)]
        if (len(choices) != 1 or state.prompt.confidence < self.min_confidence
                or state.prompt.observed_at != state.captured_at
                or choices[0].confidence < self.min_confidence
                or choices[0].observed_at != state.captured_at):
            return Recommendation(reason="確認UIの意味または対象を一意に確認できません", recognition_status="abstained")
        a = choices[0]
        return Recommendation(action=a, target=a.target, confidence=min(a.confidence, state.prompt.confidence),
                              reason=f"登録した確認UIルール: {state.prompt.value}", recognition_status="ui_rule")

    def validate_responses(self, book):
        """新しい意味別辞退には、同じ対象の一意UI規則を起動前に要求します。"""
        for rule in book.rules:
            goal = getattr(rule, "logical_response_decline", None)
            if goal is None:
                continue
            matches = [r for r in self.rules if r.prompt == goal.semantic_prompt]
            if (self.min_confidence < .98 or len(matches) != 1 or matches[0].type != rule.type
                    or matches[0].source_region != rule.source_region
                    or matches[0].card_id is not None or matches[0].target is not None):
                raise ValueError("意味別辞退の一意Cancel UI規則が不足または矛盾しています")

    def validate_hands(self,book):
        """hand3childの意味/region/CID/targetを一意に一致させます。"""
        for rule in book.rules:
            if rule.logical_hand_search_confirmation is None:continue
            matches=[r for r in self.rules if r.prompt==rule.prompt]
            if (self.min_confidence<.98 or len(matches)!=1
                    or any(getattr(matches[0],key)!=getattr(rule,key) for key in ["type","source_region","card_id","target"])):
                raise ValueError("hand-searchの一意UI規則が不足または矛盾しています")
