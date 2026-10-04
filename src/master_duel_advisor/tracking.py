from collections import deque

from .models import Event, GameState, Observation


def state_observations(state: GameState) -> dict[str, Observation]:
    result = {"turn": state.turn, "turn_player": state.turn_player, "phase": state.phase}
    for side in ["self", "opponent"]:
        player = getattr(state, side)
        result[side+".lp"] = player.lp
        result[side+".hand_count"] = player.hand_count
        result.update({side+".zones."+name: obs for name, obs in player.zones.items()})
    return result


class Tracker:
    def __init__(self, limit: int = 200):
        self.previous: GameState | None = None
        self.events: deque[Event] = deque(maxlen=limit)

    def update(self, current: GameState) -> list[Event]:
        changes = []
        if self.previous is not None:
            before = state_observations(self.previous)
            for path, after in state_observations(current).items():
                old = before.get(path)
                if old and old.value is not None and after.value is not None and old.value != after.value:
                    changes.append(Event(timestamp=current.captured_at, event="OBSERVED_CHANGE", path=path, before=old.value, after=after.value, confidence=min(old.confidence, after.confidence)))
        self.previous = current
        self.events.extend(changes)
        return changes
