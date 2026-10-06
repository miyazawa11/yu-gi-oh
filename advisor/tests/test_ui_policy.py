import time
from types import SimpleNamespace

from master_duel_advisor.models import Action, ActionType, GameState, Observation
from master_duel_advisor.pipeline import Pipeline
from master_duel_advisor.rules import ActionGenerator
from master_duel_advisor.ui_policy import UiPolicy, UiRule


def fixture_state(prompt="own_chain", animation=False):
    at = time.monotonic()
    cancel = Action(type=ActionType.CANCEL, confidence=1, source_region="action.no", observed_at=at)
    confirm = Action(type=ActionType.CONFIRM, confidence=1, source_region="action.yes", observed_at=at)
    state = GameState(sequence=0, captured_at=at, prompt=Observation(value=prompt, confidence=1, observed_at=at),
                      animation=Observation(value=animation, confidence=1, observed_at=at),
                      visible_actions=[cancel, confirm])
    return state, cancel, confirm


def test_prompt_actions_without_phase_but_never_guess_yes():
    s,no,yes = fixture_state()
    actions = tuple(ActionGenerator().generate(s, s.captured_at))
    assert actions == (no,yes)
    assert UiPolicy().decide(s,actions).action is None
    policy = UiPolicy(rules=[UiRule(prompt="own_chain", type=ActionType.CANCEL, source_region="action.no")])
    assert policy.decide(s,actions).action == no
    unknown = s.model_copy(update={"prompt": Observation()})
    assert not ActionGenerator().generate(unknown,s.captured_at)


def test_animation_blocks_ui_actions():
    s,_,_ = fixture_state(animation=True)
    assert not ActionGenerator().generate(s,s.captured_at)


def test_pipeline_routes_ui_before_combo_and_records_feedback():
    s,no,_ = fixture_state()
    class Planner:
        def observe(self,s): pass
        def decide(self,*args): raise AssertionError("UIが優先される必要があります")
        def snapshot(self): return {}
        def issued(self,a): self.pending = a
        def feedback(self,status): self.status = status
    planner = Planner()
    perception = SimpleNamespace(process=lambda f:s, cards=SimpleNamespace(get=lambda c:None),
                                 cache_hits=0, recognized_regions=0)
    pipeline = Pipeline(perception, planner=planner, ui_policy=UiPolicy(rules=[
        UiRule(prompt="own_chain", type=ActionType.CANCEL, source_region="action.no")]))
    result = pipeline.process(None)
    assert result["recommendation"]["action"]["source_region"] == "action.no"
    pipeline.action_issued(no)
    pipeline.action_feedback("changed")
    assert planner.pending == no and planner.status == "changed"


def test_prompt_diff_does_not_infer_chain_from_card_motion():
    from master_duel_advisor.tracking import Tracker
    tracker = Tracker()
    s,_,_ = fixture_state("none")
    tracker.update(s)
    current = s.model_copy(update={"prompt": Observation(value="select_material", confidence=1, observed_at=s.captured_at+1), "captured_at":s.captured_at+1})
    assert tracker.update(current)[0].event == "PROMPT_OPENED"
