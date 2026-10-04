from dataclasses import dataclass

from .cards import Card
from .models import Action, Event, GameState, Recommendation


@dataclass(frozen=True)
class DecisionContext:
    state: GameState
    history: tuple[Event, ...]
    cards: tuple[Card, ...]
    legal_actions: tuple[Action, ...]
    goal: str = "Show a supported available action; strategic optimality is unverified"


class DecisionEngine:
    def decide(self, context: DecisionContext) -> Recommendation:
        if not context.legal_actions:
            return Recommendation(reason="No fresh, confidently recognized supported action. Wait for visible information.", recognition_status="abstained")
        # No claimed strategic advantage: deterministic confidence-first baseline.
        action = sorted(context.legal_actions, key=lambda a: (-a.confidence, a.type.value, a.source_region))[0]
        return Recommendation(action=action, target=action.target, confidence=min(action.confidence, context.state.phase.confidence, context.state.turn_player.confidence), reason="Highest-confidence calibrated visible action, filtered by supported turn/phase rules. This is a baseline, not a strategic or complete-legality proof.", recognition_status="partial")
