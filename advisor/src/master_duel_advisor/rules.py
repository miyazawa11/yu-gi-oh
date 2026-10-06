from .models import Action, ActionType, GameState, Phase, Player


class ActionGenerator:
    """表示 UI に裏付けられた限定候補です。遊戯王の全ルールは判定しません。"""

    def __init__(self, minimum_confidence: float = 0.95, max_age: float = 1.5):
        self.minimum_confidence, self.max_age = minimum_confidence, max_age

    def generate(self, state: GameState, now: float) -> list[Action]:
        age = now-state.captured_at
        if age < 0 or age > self.max_age:
            return []
        if state.animation.value is True:
            return []
        modal = state.prompt.value not in {None, "none"} and state.prompt.confidence >= self.minimum_confidence and state.prompt.observed_at == state.captured_at
        independent = {ActionType.CONFIRM, ActionType.CANCEL, ActionType.SELECT_CARD, ActionType.SELECT_TARGET}
        fresh = [a for a in state.visible_actions if a.confidence >= self.minimum_confidence
                 and a.observed_at == state.captured_at and a.source_region.startswith("action.")]
        if state.phase.value is None or state.turn_player.value is None:
            return [a for a in fresh if modal and a.type in independent]
        if min(state.phase.confidence, state.turn_player.confidence) < self.minimum_confidence:
            return [a for a in fresh if modal and a.type in independent]
        if any(observation.observed_at != state.captured_at for observation in [state.phase,state.turn_player]):
            return [a for a in fresh if modal and a.type in independent]
        result = []
        for action in state.visible_actions:
            if action.confidence < self.minimum_confidence or not 0 <= now-action.observed_at <= self.max_age:
                continue
            if action.observed_at != state.captured_at or not action.source_region.startswith("action."):
                continue
            if action.type in {ActionType.NORMAL_SUMMON, ActionType.SET}:
                if state.turn_player.value != Player.SELF or state.phase.value not in {Phase.MAIN1, Phase.MAIN2}:
                    continue
            if action.type == ActionType.ATTACK:
                if state.turn_player.value != Player.SELF or state.phase.value != Phase.BATTLE:
                    continue
            if action.type == ActionType.CHANGE_PHASE and state.turn_player.value != Player.SELF:
                continue
            # 効果・選択の操作は両プレイヤーのターンで利用できる場合があります。
            result.append(action)
        return result
