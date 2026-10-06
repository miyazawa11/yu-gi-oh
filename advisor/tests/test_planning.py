from master_duel_advisor.models import (Action, ActionType, CardIdentity, GameState,
                                       Observation, Phase, Player, PlayerState)
from master_duel_advisor.planning import CardRequirement, PlanBook, PlanStep, Recipe, TurnPlanner


def state(player=Player.SELF, card="starter", at=10, opponent="known"):
    return GameState(sequence=int(at), captured_at=at,
                     turn=Observation(value=2, confidence=1, observed_at=at),
                     turn_player=Observation(value=player, confidence=1, observed_at=at),
                     phase=Observation(value=Phase.MAIN1, confidence=1, observed_at=at),
                     self=PlayerState(zones={"hand_0": Observation(
                         value=CardIdentity(card_id=card) if card else None,
                         confidence=1 if card else 0, observed_at=at)}),
                     opponent=PlayerState(zones={"monster_0": Observation(
                         value=CardIdentity(card_id=opponent), confidence=1, observed_at=at)}))


def planner():
    return TurnPlanner(PlanBook(recipes=[Recipe(id="line", goal="後続を残して展開",
        requires=[CardRequirement(zone_prefix="hand_", card_id="starter")],
        steps=[PlanStep(description="初動", type=ActionType.ACTIVATE,
                        source_region="action.starter", card_id="starter"),
               PlanStep(description="サーチ", type=ActionType.SELECT_CARD,
                        source_region="action.search", target="followup")])]))


def action(region="action.starter", at=10, target=None):
    return Action(type=ActionType.ACTIVATE if region.endswith("starter") else ActionType.SELECT_CARD,
                  source_region=region, card_id="starter", target=target,
                  confidence=1, observed_at=at)


def test_prepare_on_opponent_turn_without_acting():
    p = planner()
    s = state(Player.OPPONENT)
    p.observe(s)
    assert p.snapshot()["goal"] == "後続を残して展開"
    assert p.decide(s, (action(),)).action is None


def test_plan_advances_only_after_verified_feedback():
    p, s = planner(), state()
    p.observe(s)
    a = p.decide(s, (action(),)).action
    assert a == action()
    p.issued(a)
    assert p.decide(s, (action(),)).action is None
    assert p.index == 0
    p.feedback("unchanged")
    assert p.index == 0
    p.issued(a)
    p.feedback("changed")
    # コストで初動が手札から消えても手順を保持します。
    next_state = state(card=None, at=11)
    p.observe(next_state)
    candidate = action("action.search", 11, "followup")
    assert p.decide(next_state, (candidate,)).action == candidate
    p.issued(candidate)
    p.feedback("changed")
    p.observe(s)
    assert p.recipe is None  # 同一ターンで完了した展開を再実行しません。


def test_unrecognized_or_ambiguous_target_abstains():
    p, s = planner(), state()
    p.observe(s)
    a = action()
    assert p.decide(s, (a, a)).action is None
    p.issued(a)
    p.feedback("changed")
    assert p.decide(s, (action("action.search", target="wrong"),)).action is None


def test_opponent_change_invalidates_remaining_line():
    p, s = planner(), state()
    p.observe(s)
    p.issued(action())
    p.feedback("changed")
    p.observe(state(card=None, at=11, opponent="interruption"))
    assert p.recipe is None


def test_old_or_unknown_hand_does_not_start_plan():
    p = planner()
    p.observe(state(card=None))
    assert p.recipe is None
    p.observe(state().model_copy(update={"captured_at": 11}))
    assert p.recipe is None


def test_turn_change_and_terminal_reset_memory():
    p, s = planner(), state()
    p.observe(s)
    p.issued(action())
    p.feedback("changed")
    p.observe(state(Player.OPPONENT, card=None, at=11))
    assert p.recipe is None and p.index == 0
    p.observe(s)
    p.observe(s.model_copy(update={"terminal": Observation(value=True, confidence=1)}))
    assert p.recipe is None and not p.finished


def test_step_condition_rechecked_after_interruption():
    p, s = planner(), state()
    step = p.book.recipes[0].steps[1].model_copy(update={"requires": [
        CardRequirement(zone_prefix="hand_", card_id="followup")]})
    recipe = p.book.recipes[0].model_copy(update={"steps": [p.book.recipes[0].steps[0], step]})
    p = TurnPlanner(PlanBook(recipes=[recipe]))
    p.observe(s)
    p.issued(action())
    p.feedback("changed")
    assert p.decide(s, (action("action.search", target="followup"),)).action is None


def test_example_plan_book_loads():
    from pathlib import Path
    book = PlanBook.load(Path(__file__).parents[1] / "config" / "plan-book.example.json")
    assert book.recipes[0].steps[0].card_id == "13923"


def test_explicit_expected_state_prevents_unrelated_progress():
    p = planner()
    s = state()
    first = p.book.recipes[0].steps[0].model_copy(update={"expected_prompt": "search"})
    recipe = p.book.recipes[0].model_copy(update={"steps": [first]})
    p = TurnPlanner(PlanBook(recipes=[recipe]))
    p.observe(s)
    p.issued(action())
    assert not p.expected(action(), s)
    s = s.model_copy(update={"prompt": Observation(value="search", confidence=1, observed_at=s.captured_at)})
    assert p.expected(action(), s)
    p.feedback("unexpected_state")
    p.observe(state())
    assert p.recipe is None and p.reason == "期待状態と異なるためコンボを中断しました"
