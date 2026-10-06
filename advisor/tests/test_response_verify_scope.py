"""応答verifyだけ通常召喚探索を省略。合法手/入力guard/他goalは従来通り。"""
import json
from pathlib import Path

import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import build_pipeline,close_pipeline
from master_duel_advisor.image_io import read_image
from master_duel_advisor.strategy_rules import LogicalResponseDecline

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/solo-basic-calibration-v5"
RUN=ROOT/"artifacts/baseline-tester/SOLO_END_PILOT_v4_20261006/screenshots"
NORMAL=ROOT/"artifacts/baseline-tester/ASH_NORMAL_INSPECT_LAYOUT2_TRAIN_v2_20261006/menu/frame-0000.png"


def pipeline(base=BASE):
    return build_pipeline(base/"calibration.json",ROOT/"data/decks/thunder-dragon-review/cards.sqlite3",
        base/"solo-route.json",base/"ui-rules.json")


def goal(p):
    return next(g for g in p.perception.response_goals if g.kind=="opponent_turn_end")


@pytest.mark.parametrize("case",["match","ledger_other_kind","ledger_missing","ledger_wrong_mode","normal_rule","no_action","fake_goal"])
def test_only_declared_current_action_and_matching_active_ledger_grant_scope(tmp_path,case):
    from test_agent_loop import setup
    from test_response_decline import response_book
    loop,_,_=setup(tmp_path);book=response_book();rule=book.rules[0]
    loop.pipeline.planner=type("Planner",(),{"rule_for":lambda self,action:rule})()
    loop.current_action=loop.pipeline.action
    spec=rule.logical_response_decline.model_dump(mode="json")
    loop.telemetry.active={"response_decline":dict(spec)}
    if case=="ledger_other_kind":loop.telemetry.active["response_decline"]["kind"]="opponent_summon_success"
    elif case=="ledger_missing":loop.telemetry.active={}
    elif case=="ledger_wrong_mode":loop.telemetry.active["response_decline"]["evidence_mode"]="observed_self_draw"
    elif case=="normal_rule":rule=rule.model_copy(update={"logical_response_decline":None})
    elif case=="no_action":loop.current_action=None
    elif case=="fake_goal":rule=rule.model_copy(update={"logical_response_decline":object()})
    assert (loop._response_verification_scope() is not None)==(case=="match")


@pytest.mark.parametrize("scope",[True,"response",{},"other_goal"])
def test_perception_rejects_unregistered_or_forged_scope(scope):
    p=pipeline()
    try:
        value=goal(p).model_copy(update={"cancel_region":"action.wrong"}) if scope=="other_goal" else scope
        with pytest.raises(ValueError):p.perception.process(Frame(read_image(RUN/"after-0001.png"),0,1),verification_scope=value)
    finally:close_pipeline(p)


def test_scope_skips_only_search_retains_registry_generic_caption_draw_and_stats(monkeypatch):
    p=pipeline();counts={"bank":0,"guard":0,"registry":0,"caption":0,"draw":0,"crop":0}
    try:
        objects=[(p.perception.inspect_detector,"recognize","bank"),(p.perception.inspect_detector,"assert_assets_unchanged","guard"),
            (p.perception.inspect_registry,"recognize","registry"),(p.perception.cancel_caption,"detect","caption"),
            (p.perception.draw_overlay,"detect","draw")]
        for obj,attr,key in objects:
            original=getattr(obj,attr)
            def wrapper(*args,_original=original,_key=key,**kwargs):
                counts[_key]+=1
                return _original(*args,**kwargs)
            monkeypatch.setattr(obj,attr,wrapper)
        signatures=[]
        for file in ["before-0000.png","after-0001.png"]:
            pixels=read_image(RUN/file)
            full=p.perception.process(Frame(pixels,0,1))
            scoped=p.perception.process(Frame(pixels,0,2),verification_scope=goal(p))
            signatures.append(([full.phase.value,full.turn_player.value,full.prompt.value,full.terminal.value],
                [scoped.phase.value,scoped.turn_player.value,scoped.prompt.value,scoped.terminal.value]))
            for key in ["response.prompt.opponent_turn_end","response.prompt.opponent_summon_success",
                "response.cancel_enabled.opponent_turn_end","response.outcome.self_draw"]:
                assert full.facts[key].value==scoped.facts[key].value
            span=next(s for s in p.perception.stage_spans if s["stage"]=="normal_ui_bank")
            assert span["skipped_search"] and span["verification_scope"]==goal(p).model_dump(mode="json")
        assert all(full==scoped for full,scoped in signatures)
        assert counts["bank"]==2 and counts["guard"]==4
        assert counts["registry"]==counts["caption"]==counts["draw"]==4
    finally:close_pipeline(p)


def test_scope_does_not_reuse_cached_normal_facts_or_coordinate_proof():
    p=pipeline()
    try:
        pixels=read_image(NORMAL)
        full=p.perception.process(Frame(pixels,0,1,capture_source="saved_image"))
        assert any(a.type.value=="NORMAL_SUMMON" for a in full.visible_actions)
        crops=p.perception.calibration.crop_regions(pixels)
        for name in ["fact.inspect_context.hand_selected","fact.inspect_context.summon_enabled"]:
            p.perception._cache[name]=(crops[name].copy(),"true",1.)
        scoped=p.perception.process(Frame(pixels,0,2,capture_source="saved_image"),verification_scope=goal(p))
        for key in ["inspect_context.hand_selected","inspect_context.summon_enabled"]:
            assert scoped.facts[key].value is None and scoped.facts[key].confidence==0
            assert scoped.facts[key].observed_at==scoped.captured_at==0 and scoped.facts[key].source=="not_in_response_verification_scope"
        assert not any(a.type.value=="NORMAL_SUMMON" or a.coordinate_proof is not None for a in scoped.visible_actions)
        again=p.perception.process(Frame(pixels,0,3,capture_source="saved_image"))
        assert any(a.type.value=="NORMAL_SUMMON" for a in again.visible_actions)
    finally:close_pipeline(p)


def test_skipped_bank_still_rejects_asset_mutation(tmp_path):
    from master_duel_advisor.ui_evidence_bank import UiEvidenceBank
    p=pipeline()
    try:
        source=p.perception.inspect_detector.config_path
        raw=json.loads(source.read_text(encoding="utf-8"))
        for field in ["detectors","hand_calibrations"]:
            for entry in raw[field]:entry["path"]=str((source.parent/entry["path"]).resolve())
        asset=tmp_path/"bank.json";asset.write_text(json.dumps(raw),encoding="utf-8")
        p.perception.inspect_detector=UiEvidenceBank(asset)
        asset.write_bytes(asset.read_bytes()+b"changed")
        with pytest.raises(ValueError):p.perception.process(Frame(read_image(RUN/"after-0001.png"),0,1),verification_scope=goal(p))
        span=next(s for s in p.perception.stage_spans if s["stage"]=="normal_ui_bank")
        assert span["error"]=="ValueError" and span["end"]>=span["start"]
    finally:close_pipeline(p)


def test_nested_bank_span_is_not_added_twice_to_internal_or_verify_union(tmp_path):
    from test_response_decline import response_case
    tel,_,_=response_case(tmp_path)
    tel.spans=[{"stage":"capture","start":.9,"end":1},
        {"stage":"recognition","start":1,"end":1.1},
        {"stage":"verify","start":1.1,"end":2},
        {"stage":"recognition","start":1.2,"end":1.4},
        {"stage":"normal_ui_bank","start":1.22,"end":1.39}]
    tel.finish("interrupted","Verification failure","synthetic",end=2)
    row=tel.records[0]
    assert row["system_internal_ms"]==pytest.approx(400)
    assert row["verification_residual_ms"]==pytest.approx(700)
    assert row["child_stage_ms"]["normal_ui_bank"]==pytest.approx(170)
