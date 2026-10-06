from dataclasses import dataclass

from .cards import Card
from .models import Action, Event, GameState, Recommendation


@dataclass(frozen=True)
class DecisionContext:
    state: GameState
    history: tuple[Event, ...]
    cards: tuple[Card, ...]
    legal_actions: tuple[Action, ...]
    goal: str = "対応範囲の選択可能な行動を示します。戦略的な最適性は未検証です"


class DecisionEngine:
    def decide(self, context: DecisionContext) -> Recommendation:
        if not context.legal_actions:
            return Recommendation(reason="新しく十分な信頼度で認識できた対応行動がありません。画面上の情報を待ってください。", recognition_status="abstained")
        # 戦略上の優位性は主張せず、信頼度を優先する決定的な基準実装とします。
        action = sorted(context.legal_actions, key=lambda a: (-a.confidence, a.type.value, a.source_region))[0]
        return Recommendation(action=action, target=action.target, confidence=min(action.confidence, context.state.phase.confidence, context.state.turn_player.confidence), reason="表示中の校正済み候補をターン・フェイズの対応ルールで絞り込み、最も信頼度の高い行動を選びました。基準実装であり、戦略的な最善手や全ルールの合法性は保証しません。", recognition_status="partial")
