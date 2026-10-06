import json
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.materials import Material, valid_materials
from master_duel_advisor.models import Action, GameState, Observation
from master_duel_advisor.pipeline import Pipeline
from master_duel_advisor.strategy_rules import RulePlanner, StrategyBook, load_planner

BOOK = Path(__file__).resolve().parents[1] / "data/decks/thunder-dragon-review/strategy-book.json"


def observation(value, at):
    return Observation(value=value, confidence=1, observed_at=at, source="verified_fixture")


def fixture(key="dark_hand", at=None):
    at = time.monotonic() if at is None else at
    p = load_planner(BOOK)
    p.book = p.book.model_copy(update={"inference_mode": "strict"})
    rule = next(r for r in p.book.rules if r.id == key)
    a = Action(type=rule.type, card_id=rule.card_id, target=rule.target,
               source_region=rule.source_region, confidence=1, observed_at=at)
    s = GameState(sequence=1, captured_at=at, turn=observation(1, at),
        turn_player=observation(rule.players[0], at), phase=observation(rule.phases[0], at),
        prompt=observation(rule.prompt, at), animation=observation(False, at),
        terminal=observation(False, at), facts={k: observation(v, at) for k,v in rule.facts.items()},
        self={"zones": {r.zone_prefix+"0": observation({"card_id":r.card_id}, at) for r in rule.requires}},
        visible_actions=[a])
    return p, s, a


def mat(instance, **kwargs):
    return Material(**dict(dict(instance=instance, card_id="test", name=instance, race="Thunder", effect=True), **kwargs))


def test_book_covers_all_deck_cards():
    data = json.loads(BOOK.read_text(encoding="utf-8"))
    p = RulePlanner(StrategyBook.model_validate(data))
    profile = json.loads(BOOK.with_name("deck-profile.json").read_text(encoding="utf-8"))
    assert {r.card_id for r in p.book.rules if r.card_id} == set(profile["card_ids"])
    assert len(p.book.rules) == 94


@pytest.mark.parametrize("key", ["matrix_hand", "dark_hand", "hawk_hand", "roar_hand"])
def test_shared_once_per_turn_never_assumed(key):
    p, s, a = fixture(key)
    assert p.decide(s, [a]).action == a
    group = "unused." + a.card_id
    for value in [None, "false"]:
        facts = dict(s.facts)
        if value is None:
            del facts[group]
        else:
            facts[group] = observation(value, s.captured_at)
        assert p.decide(s.model_copy(update={"facts": facts}), [a]).action is None


@pytest.mark.parametrize("field", ["phase", "turn_player", "prompt", "animation", "terminal"])
def test_unknown_or_stale_context_blocks(field):
    p, s, a = fixture()
    assert p.decide(s.model_copy(update={field: Observation()}), [a]).action is None
    obs = getattr(s, field).model_copy(update={"observed_at": s.captured_at-1})
    assert p.decide(s.model_copy(update={field: obs}), [a]).action is None


def test_unknown_action_duplicate_and_pending_block():
    p, s, a = fixture()
    assert not p.filter_actions(s, [a.model_copy(update={"source_region":"action.unknown"})])
    assert not p.filter_actions(s, [a, a])
    p.issued(a)
    assert not p.filter_actions(s, [a])
    p.feedback("changed")
    # 使用履歴を新たな画面で確認し、画面遷移を効果の成功に置き換えない。
    assert not p.filter_actions(s.model_copy(update={"facts":{}}), [a])


def test_stale_fact_and_wrong_prompt_block():
    p, s, a = fixture("roar_trigger")
    assert p.decide(s, [a]).action == a
    assert not p.filter_actions(s.model_copy(update={"prompt":observation("trigger.dark_trigger", s.captured_at)}), [a])
    facts = {k: v.model_copy(update={"observed_at":s.captured_at-1}) for k,v in s.facts.items()}
    assert not p.filter_actions(s.model_copy(update={"facts":facts}), [a])


def test_priority_is_not_recognition_confidence():
    p, s, a = fixture("dark_hand")
    _, s2, a2 = fixture("td_discard", s.captured_at)
    s = s.model_copy(update={"phase":s2.phase, "facts":{**s.facts, **s2.facts},
        "self": s.self.model_copy(update={"zones":{**s.self.zones,"hand_1":next(iter(s2.self.zones.values()))}})})
    a2 = a2.model_copy(update={"confidence":.99})
    assert p.decide(s, [a, a2]).action == a2


def test_material_proof_required_even_with_true_facts():
    p, s, a = fixture("colossus")
    assert not p.filter_actions(s, [a])
    s = s.model_copy(update={"material_sets":{"colossus": observation([mat("one")], s.captured_at)}})
    assert p.filter_actions(s, [a])
    s = s.model_copy(update={"material_sets":{"colossus": observation([mat("token", token=True, effect=False)], s.captured_at)}})
    assert not p.filter_actions(s, [a])


def test_link_material_constraints():
    token = mat("token").model_copy(update={"effect":False, "token":True})
    normal = mat("normal")
    assert valid_materials("summer", [token, normal])
    assert not valid_materials("verte", [token, normal])
    assert not valid_materials("colossus", [token])
    assert not valid_materials("ogre", [mat("l2", link=2), mat("l2b", link=2)])
    assert not valid_materials("sword", [mat("l2", link=2), mat("l2b", link=2)])
    assert valid_materials("sword", [mat("l2", link=2), normal, mat("other")])
    assert valid_materials("access", [mat("l3", link=3), normal])
    assert not valid_materials("unicorn", [mat("l3", link=3), normal])
    assert not valid_materials("summer", [normal, normal])
    assert not valid_materials("sheep", [normal, normal.model_copy(update={"instance":"other"})])


def test_fusion_zone_and_name_constraints():
    td = mat("td", zone="graveyard").model_copy(update={"name":"サンダー・ドラゴン", "thunder_dragon":True})
    dark = mat("dark", zone="banished", thunder_dragon=True)
    assert valid_materials("fusion_colossus", [td, dark])
    assert not valid_materials("fusion_colossus", [td.model_copy(update={"zone":"hand"}), dark])
    assert not valid_materials("fusion_colossus", [td, dark.model_copy(update={"face_up":False})])
    assert not valid_materials("fusion_titan", [td, dark])
    assert valid_materials("fusion_titan", [td, dark, mat("roar", thunder_dragon=True)])
    assert not valid_materials("titan_alternative", [mat("hand", zone="hand"), mat("titan", fusion=True).model_copy(update={"card_id":"13924"})])


def test_pipeline_fallback_and_timeout_cannot_bypass_guards():
    p, s, a = fixture()
    s = s.model_copy(update={"facts":{}})
    perception = SimpleNamespace(process=lambda frame:s, cards=SimpleNamespace(get=lambda key:None),
                                 cache_hits=0, recognized_regions=0)
    class NoFallback:
        calls = 0
        def poll(self, *args):
            raise AssertionError("禁止候補をLLMへ渡してはいけません")
        request = poll
    pipeline = Pipeline(perception, planner=p, strategy_fallback=NoFallback(), clock=lambda:100)
    frame = Frame(sequence=s.sequence, captured_at=s.captured_at, pixels=np.zeros((2,2,3), dtype=np.uint8))
    snapshot = pipeline.process(frame)
    assert snapshot["recommendation"]["action"] is None
    assert snapshot["legal_actions"] == []
    assert snapshot["plan"]["blocked"]
    assert pipeline._force_choice(s, [a]).action is None
    pipeline.decision_started = 80
    assert pipeline.process(frame)["recommendation"]["action"] is None


def test_valid_candidate_still_forced_at_deadline():
    p, s, a = fixture()
    perception = SimpleNamespace(cards=SimpleNamespace(get=lambda key:None))
    pipeline = Pipeline(perception, planner=p)
    assert pipeline._force_choice(s, [a]).action == a


def test_registered_trigger_prompt_uses_deck_rule_without_legacy_ui_book():
    p, s, a = fixture("roar_trigger")
    perception = SimpleNamespace(process=lambda frame:s, cards=SimpleNamespace(get=lambda key:None),
                                 cache_hits=0, recognized_regions=0)
    pipeline = Pipeline(perception, planner=p)
    frame = Frame(sequence=s.sequence, captured_at=s.captured_at, pixels=np.zeros((2,2,3), dtype=np.uint8))
    snapshot = pipeline.process(frame)
    assert snapshot["recommendation"]["action"]["source_region"] == a.source_region
    assert snapshot["recommendation"]["recognition_status"] == "deck_rule"


def test_disabled_deck_routes():
    for key in ["ogre_link", "driver_normal"]:
        p, s, a = fixture(key)
        assert not p.filter_actions(s, [a])


def provisional(key="dark_hand"):
    p, s, a = fixture(key)
    p.book = p.book.model_copy(update={"inference_mode":"provisional"})
    return p, s.model_copy(update={"facts":{}, "self":s.self.model_copy(update={"zones":{}})}), a


def test_provisional_unknown_facts_are_logged_without_modifying_observation():
    p, s, a = provisional()
    recommendation = p.decide(s, [a])
    assert recommendation.action == a
    assert recommendation.recognition_status == "deck_rule_inferred"
    assert "unused.13906" in p.snapshot()["assumptions"][a.source_region]
    assert s.facts == {}


def test_provisional_known_false_and_invalid_materials_still_block():
    p, s, a = provisional()
    s = s.model_copy(update={"facts":{"unused.13906":observation("false", s.captured_at)}})
    assert not p.filter_actions(s, [a])
    p, s, a = provisional("colossus")
    assert p.filter_actions(s, [a])
    s = s.model_copy(update={"material_sets":{"colossus":observation([mat("token", token=True, effect=False)], s.captured_at)}})
    assert not p.filter_actions(s, [a])


def test_provisional_ui_and_execution_gates_remain():
    p, s, a = provisional()
    for field, value in [("animation",True),("terminal",True),("phase","END"),("prompt","unrelated")]:
        # dark_handは全フェイズ対応なのでフェイズ未知で検証。
        obs = Observation() if field == "phase" else observation(value, s.captured_at)
        assert not p.filter_actions(s.model_copy(update={field:obs}), [a])
    assert not p.filter_actions(s, [a.model_copy(update={"confidence":.5})])
    assert not p.filter_actions(s, [a.model_copy(update={"source_region":"action.unknown"})])


def test_provisional_used_effect_is_not_repeated_and_resets_on_turn():
    p, s, a = provisional()
    p.observe(s)
    p.issued(a)
    p.feedback("changed")
    assert not p.filter_actions(s, [a])
    s = s.model_copy(update={"turn":observation(2, s.captured_at)})
    p.observe(s)
    assert p.filter_actions(s, [a])


def test_provisional_normal_summon_and_verte_lock():
    p, s, a = provisional("matrix_normal")
    p.issued(a)
    p.feedback("unchanged")
    assert not p.filter_actions(s, [a])
    p, s, a = provisional("verte_fusion")
    p.issued(a)
    p.feedback("changed")
    _, colossus_state, colossus = provisional("colossus")
    assert not p.filter_actions(colossus_state, [colossus])


def test_provisional_timeout_selects_candidate_and_preserves_assumption_log():
    p, s, a = provisional()
    pipeline = Pipeline(SimpleNamespace(cards=SimpleNamespace(get=lambda key:None)), planner=p)
    assert pipeline._force_choice(s, [a]).action == a
    assert p.snapshot()["assumptions"][a.source_region]
