import pytest

from master_duel_advisor.cards import Card, CardDatabase
from master_duel_advisor.decision import DecisionContext, DecisionEngine
from master_duel_advisor.models import Action, ActionType, GameState, Observation, Phase, Player, PlayerState
from master_duel_advisor.rules import ActionGenerator
from master_duel_advisor.tracking import Tracker


def make_state(action_type=ActionType.NORMAL_SUMMON,phase=Phase.MAIN1,player=Player.SELF):
    return GameState(sequence=1,captured_at=10,phase=Observation(value=phase,confidence=1,observed_at=10),turn_player=Observation(value=player,confidence=1,observed_at=10),visible_actions=[Action(type=action_type,confidence=1,source_region="action.primary",observed_at=10)])


@pytest.mark.parametrize("action,phase,player,allowed",[
    (ActionType.NORMAL_SUMMON,Phase.MAIN1,Player.SELF,True),
    (ActionType.NORMAL_SUMMON,Phase.BATTLE,Player.SELF,False),
    (ActionType.NORMAL_SUMMON,Phase.MAIN1,Player.OPPONENT,False),
    (ActionType.SET,Phase.MAIN2,Player.SELF,True),
    (ActionType.ATTACK,Phase.BATTLE,Player.SELF,True),
    (ActionType.ATTACK,Phase.BATTLE,Player.OPPONENT,False),
    (ActionType.ATTACK,Phase.MAIN1,Player.SELF,False),
    (ActionType.ACTIVATE,Phase.MAIN1,Player.OPPONENT,True),
    (ActionType.CHANGE_PHASE,Phase.MAIN1,Player.OPPONENT,False),
    (ActionType.SELECT_TARGET,Phase.BATTLE,Player.OPPONENT,True),
])
def test_rule_matrix(action,phase,player,allowed):
    assert bool(ActionGenerator().generate(make_state(action,phase,player),10)) == allowed


@pytest.mark.parametrize("now",[9,12])
def test_stale_or_future_state_abstains(now):
    assert ActionGenerator().generate(make_state(),now) == []


@pytest.mark.parametrize("update",[{"phase":Observation()}, {"turn_player":Observation()}, {"phase":Observation(value=Phase.MAIN1,confidence=.5)}, {"visible_actions":[]}])
def test_incomplete_state_no_invented_actions(update):
    assert ActionGenerator().generate(make_state().model_copy(update=update),10) == []


def test_action_age_and_provenance():
    state = make_state()
    for update in [{"confidence":.6},{"observed_at":9},{"source_region":"inferred"}]:
        changed = state.visible_actions[0].model_copy(update=update)
        assert ActionGenerator().generate(state.model_copy(update={"visible_actions":[changed]}),10) == []


def test_old_phase_observation_cannot_authorize_current_button():
    state=make_state()
    stale_phase=state.phase.model_copy(update={"observed_at":8})
    assert ActionGenerator().generate(state.model_copy(update={"phase":stale_phase}),10)==[]


def test_structured_decision_restricts_to_candidates():
    engine = DecisionEngine()
    state = make_state()
    assert engine.decide(DecisionContext(state,(),(),())).action is None
    candidates = tuple(ActionGenerator().generate(state,10))
    result=engine.decide(DecisionContext(state,(),(),candidates))
    assert result.action in candidates
    assert result.model_dump(mode="json")["action"]["type"] == "NORMAL_SUMMON"


def test_tracking_known_changes_unknown_barrier_and_history_bound():
    tracker=Tracker(limit=2)
    def state(lp,seq):
        return GameState(sequence=seq,captured_at=seq,self=PlayerState(lp=Observation(value=lp,confidence=1 if lp is not None else 0)))
    assert tracker.update(state(8000,0)) == []
    change=tracker.update(state(5200,1))
    assert len(change)==1 and change[0].event=="OBSERVED_CHANGE"
    assert change[0].before==8000 and change[0].after==5200
    assert tracker.update(state(None,2)) == []
    assert tracker.update(state(0,3)) == []
    tracker.update(state(100,4))
    tracker.update(state(200,5))
    assert len(tracker.events)==2


def test_sqlite_persistence_and_upsert(tmp_path):
    path=tmp_path/"cards.sqlite3"
    card=Card(card_id="1",name="Alpha",type="monster",effect_text="A",level=1,atk=300,defense=200)
    db=CardDatabase(path)
    db.import_cards([card])
    assert db.get("1")==card
    assert db.get("unseen") is None
    db.import_cards([card.model_copy(update={"name":"Beta"})])
    db.close()
    db=CardDatabase(path)
    try:
        assert db.get("1").name=="Beta"
    finally:
        db.close()
