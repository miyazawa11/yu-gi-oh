import json
from threading import Event

import pytest
from pydantic import ValidationError

from master_duel_advisor.card_graph import CardGraph, Edge
from master_duel_advisor.dataset import export_dataset
from master_duel_advisor.deck import DeckProfile
from master_duel_advisor.llm_fallback import StrategyFallback, semantic_key
from master_duel_advisor.models import Action, ActionType, GameState


def state(at=10):
    action = Action(type=ActionType.ACTIVATE, source_region="action.activate", card_id="a",
                    confidence=1, observed_at=at)
    return GameState(sequence=1, captured_at=at, visible_actions=[action]), action


def test_graph_bounds_cycles_and_upserts(tmp_path):
    graph = CardGraph(tmp_path / "graph.sqlite3")
    def edge(a,b):
        return Edge(source=a,target=b,relation="SEARCH",condition="公開条件を別途確認",source_url="fixture")
    graph.import_edges([edge("a","b"),edge("b","c"),edge("b","a")])
    graph.import_edges([edge("a","b")])
    assert len(graph.outgoing("a")) == 1
    assert not list(graph.paths("a","c",max_depth=1))
    assert [e.target for e in list(graph.paths("a","c"))[0]] == ["b","c"]
    assert not list(graph.paths("a","a"))
    with pytest.raises(ValueError): list(graph.paths("a","c",max_nodes=0))
    graph.close()


def test_deck_and_dataset_preserve_unknown_and_skip_failed(tmp_path):
    profile = DeckProfile(name="試験",card_ids=["a"],generic_card_ids=["b","a"])
    assert profile.recognition_ids == {"a","b"}
    with pytest.raises(ValidationError): DeckProfile(name="試験",card_ids=[])
    log = tmp_path / "actions.jsonl"
    entries = [{"status":status,"state_before":{"unknown":None},"action":{"type":"ACTIVATE"}}
               for status in ["changed","unchanged","input_blocked","duel_ended"]]
    log.write_text("\n".join(json.dumps(e) for e in entries),encoding="utf-8")
    out = tmp_path / "samples.jsonl"
    assert export_dataset(log,out)["samples"] == 2
    assert json.loads(out.read_text().splitlines()[0])["state"]["unknown"] is None
    with pytest.raises(ValueError): export_dataset(log,log)


def test_fallback_is_nonblocking_budgeted_and_uses_no_images():
    entered,release = Event(),Event()
    s,a = state()
    def provider(payload,schema):
        assert "pixels" not in payload and "properties" in schema
        entered.set()
        assert release.wait(2)
        return dict(type=a.type,source_region=a.source_region,card_id="a",target=None,
                    confidence=1,reason="公開状態の例外判断")
    fallback = StrategyFallback(provider,max_calls=1,cooldown=0)
    try:
        assert fallback.request(s,"unfamiliar_board")
        assert entered.wait(1)
        assert fallback.poll(s,[a]) is None
        assert not fallback.request(s,"unfamiliar_board")
        release.set()
        fallback.future.result(timeout=2)
        assert fallback.poll(s,[a]).action == a
        assert not fallback.request(s,"unfamiliar_board")
    finally:
        release.set()
        fallback.close()


@pytest.mark.parametrize("invalid",["stale","illegal","schema","timeout"])
def test_fallback_discards_invalid_responses(invalid):
    s,a = state()
    ticks = [0.0]
    answer = dict(type=a.type,source_region=a.source_region,card_id="a",target=None,confidence=1,reason="試験")
    if invalid == "schema": answer["extra"] = True
    fallback = StrategyFallback(lambda *_:answer,clock=lambda:ticks[0],cooldown=0)
    try:
        assert fallback.request(s,"low_confidence")
        fallback.future.result(timeout=2)
        if invalid == "stale": s = s.model_copy(update={"visible_actions":[]})
        if invalid == "timeout": ticks[0] = 6
        assert fallback.poll(s,[] if invalid == "illegal" else [a]) is None
        assert fallback.last_error
    finally: fallback.close()


def test_semantic_key_ignores_observation_clock_but_not_actions():
    first,_ = state(10)
    refreshed,_ = state(11)
    assert semantic_key(first) == semantic_key(refreshed)
    assert semantic_key(first) != semantic_key(first.model_copy(update={"visible_actions":[]}))


def test_pipeline_fallback_only_after_local_abstention_and_outside_modals():
    import time
    from types import SimpleNamespace
    from master_duel_advisor.models import Observation, Recommendation
    from master_duel_advisor.pipeline import Pipeline
    s,a = state(time.monotonic())
    s = s.model_copy(update={"prompt":Observation(value="none",confidence=1,observed_at=s.captured_at)})
    class Fallback:
        calls = 0
        def poll(self,*args): return None
        def request(self,*args): self.calls += 1
    fallback = Fallback()
    perception = SimpleNamespace(process=lambda _:s,cards=SimpleNamespace(get=lambda _:None),cache_hits=0,recognized_regions=0)
    pipeline = Pipeline(perception,rules=SimpleNamespace(generate=lambda *_:[a]),strategy_fallback=fallback)
    pipeline.engine = SimpleNamespace(decide=lambda _:Recommendation(reason="戦略未解決",recognition_status="abstained"))
    pipeline.process(None)
    assert fallback.calls == 1
    s = s.model_copy(update={"prompt":Observation(value="unknown_modal",confidence=1,observed_at=s.captured_at)})
    pipeline.process(None)
    assert fallback.calls == 1
