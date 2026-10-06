"""目的単位/同一時計/欠測/誤クリックの回帰。実ゲームの性能標本ではありません。"""
import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.models import Action, GameState, Observation
from master_duel_advisor.telemetry import ActionTelemetry, MeasuredCapture, summarize, union_ms, value_hash, FINGERPRINT_FIELDS


class Clock:
    def __init__(self):
        self.value = 1.0

    def __call__(self):
        return self.value


def state(at, count=None, phase="MAIN1", turn=1, player="self"):
    def obs(value):
        return Observation(value=value, confidence=1, observed_at=at)
    return GameState(sequence=int(at*1000), captured_at=at, facts={"count.self.field.13923": obs(str(count))} if count is not None else {},
                     phase=obs(phase), turn=obs(turn), turn_player=obs(player))


def rule(start=False, end=False, **extra):
    return SimpleNamespace(id="open" if start else "confirm", logical_action="summon", logical_category="SPECIAL_SUMMON",
                           logical_start=start, logical_end=end, logical_count_fact="count.self.field.13923", **extra)


def begin(t, at, r, count=0):
    action = Action(type="CONFIRM", confidence=1, source_region="action."+r.id, observed_at=at)
    frame = Frame(np.zeros((2,2,3), np.uint8), at, int(at*1000), capture_start=at-.1, capture_end=at)
    t.begin_step(action, r, state(at, count), frame, {})
    return frame


def test_union_does_not_double_count_nested_spans():
    assert union_ms([{"start":1, "end":4}, {"start":2, "end":3}, {"start":3, "end":5}]) == 4000


def test_many_ui_steps_one_logical_success_and_confirm_time(tmp_path):
    clock = Clock()
    t = ActionTelemetry(tmp_path, clock, "synthetic")
    begin(t, 1, rule(start=True))
    t.input_result(True, (10,20))
    clock.value = 1.3
    t.complete_step("changed", rule(), state(1.3, 0))
    assert not t.records
    begin(t, 1.4, rule(end=True))
    t.input_result(True, (20,30))
    t.spans = [{"stage":"capture", "start":.5, "end":1.0},
               {"stage":"verify", "start":1.5, "end":2.0},
               {"stage":"recognition", "start":1.8, "end":1.9}]
    clock.value = 10  # 後続保存時刻は完了時刻にならない。
    t.complete_step("changed", rule(end=True), state(2, 1), at=2)
    row = t.records[0]
    assert row["steps_count"] == 2 and row["input_count"] == 2
    assert row["result"] == "success" and row["verify_end"] == 2
    assert row["total_ms"] == pytest.approx(1100)
    assert row["spans"][0]["start"] == .9
    assert row["game_wait_estimate_ms"] == pytest.approx(400)


@pytest.mark.parametrize("before,after", [(None,1),(1,1),(1,None)])
def test_presence_unknown_or_unchanged_cannot_pass(tmp_path, before, after):
    t = ActionTelemetry(tmp_path, Clock(), "synthetic")
    begin(t, 1, rule(start=True,end=True), before)
    t.complete_step("changed", rule(end=True), state(2,after), at=2)
    row=t.records[0]
    assert row["result"] == "unverified"
    assert row["verify_end"] is None and row["successful_e2e_ms"] is None


def test_stale_count_not_success(tmp_path):
    t=ActionTelemetry(tmp_path,Clock())
    begin(t,1,rule(start=True,end=True))
    after=state(2,1).model_copy(update={"facts":state(1,1).facts})
    t.complete_step("changed",rule(end=True),after,at=2)
    assert t.records[0]["result"] == "unverified"


def test_stop_and_input_error_are_not_lost(tmp_path):
    clock=Clock();t=ActionTelemetry(tmp_path,clock)
    begin(t,1,rule(start=True));t.input_result(None,(1,2))
    clock.value=2
    t.complete_step("input_error_outcome_unknown",rule(),None)
    begin(t,2,rule(start=True));clock.value=3;t.close("esc")
    assert len(t.records)==2
    assert t.records[0]["failure_category"] == "Input failure"
    assert t.records[1]["result"] == "interrupted"
    assert (tmp_path/"telemetry-spans.jsonl").exists()


def test_reused_capture_and_llm_cycle_anchor(tmp_path):
    clock=Clock();t=ActionTelemetry(tmp_path,clock)
    t.event("fallback");clock.value=2
    r=rule(start=True)
    action=Action(type="CONFIRM",confidence=1,source_region="action.open",observed_at=2)
    frame=Frame(np.zeros((2,2,3),np.uint8),2,2,capture_start=1.9,capture_end=2)
    t.begin_step(action,r,state(2,0),frame,{},capture_anchor=.9)
    assert t.active["capture_start"] == .9 and t.active["fallback_used"]
    t.import_spans([{"stage":"recognition","start":1,"end":1.1}])
    t.import_spans([{"stage":"recognition","start":1,"end":1.1}])
    assert len(t.spans)==1


def test_capture_none_exception_and_original_clock(tmp_path):
    clock=Clock();t=ActionTelemetry(tmp_path,clock)
    class Source:
        def read(self):
            clock.value=1.1
            return Frame(np.zeros((2,2,3),np.uint8),1.1,1)
    wrapped=MeasuredCapture(Source(),t)
    frame=wrapped.read()
    assert frame.capture_start==1 and frame.capture_end==1.1
    assert frame.captured_at==1.1
    with pytest.raises(ValueError):
        with t.span("recognition"):
            raise ValueError("failure")
    assert t.spans[-1]["error"] == "ValueError"


@pytest.mark.parametrize("goal,after,success", [
    ({"logical_phase":"BATTLE"},dict(phase="BATTLE"),True),
    ({"logical_phase":"BATTLE"},dict(phase="MAIN1"),False),
    ({"logical_turn_advance":True},dict(turn=2,player="opponent"),True),
    ({"logical_turn_advance":True},dict(turn=1,player="opponent"),False),
])
def test_phase_and_turn_goals_need_fresh_changed_state(tmp_path,goal,after,success):
    t=ActionTelemetry(tmp_path,Clock())
    begin(t,1,rule(start=True,end=True,**goal))
    t.complete_step("changed",rule(end=True,**goal),state(2,**after),at=2)
    assert (t.records[0]["result"] == "success") is success


def sample(i, mode="live_autonomous", result="success"):
    return {"schema":"logical-action-v1","action_id":str(i),"mode":mode,"result":result,
            "admission":"scheduled_trial","total_ms":2000,"measurement_complete":True,"classified":True,"category":"SPECIAL_SUMMON",
            "input_count":2,"retry_count":0,"fallback_used":False,"failure_reason":None,
            "steps":[{"step_id":str(i)+"a","input_sent":True},{"step_id":str(i)+"b","input_sent":True}]}


def write_rows(path,rows):
    path.write_text("\n".join(json.dumps(r) for r in rows),encoding="utf-8")
    return path


def test_legacy_100_samples_reviews_remain_reference_only(tmp_path):
    rows=[sample(i) for i in range(100)]
    path=write_rows(tmp_path/"actions.jsonl",rows)
    report=summarize([path],required_categories=["SPECIAL_SUMMON"], required_step_types=[])
    assert not report["passed"] and report["misclick_rate"] is None
    reviews=[{"step_id":s["step_id"],"misclick":False,"evidence":"test-fixture-only","reviewer":"test"} for r in rows for s in r["steps"]]
    rp=write_rows(tmp_path/"reviews.jsonl",reviews)
    report = summarize([path],required_categories=["SPECIAL_SUMMON"], required_step_types=[],reviews=[rp])
    assert not report["passed"] and not report["gates"]["acceptance_cohort_integrity"]
    assert report["misclick_rate"] == 0
    reviews[0]["misclick"]=True;reviews[1]["misclick"]=True
    write_rows(rp,reviews)
    report=summarize([path],required_categories=["SPECIAL_SUMMON"], required_step_types=[],reviews=[rp])
    assert report["misclick_rate"]==.01 and not report["passed"]


def test_failures_not_removed_assisted_excluded_and_coverage_required(tmp_path):
    rows=[sample(i) for i in range(99)]+[sample(99,result="interrupted"),sample(100,mode="assisted")]
    rows[99]["total_ms"]=10000
    path=write_rows(tmp_path/"log.jsonl",rows)
    report=summarize([path])
    assert report["samples"]==100 and report["excluded_modes"]=={"assisted":1}
    assert report["average_ms"]==2080 and report["successful_e2e_ms"]["average_ms"]==2000
    assert report["success_rate"]==.99 and not report["gates"]["coverage"]
    rows[0]["total_ms"]=None
    write_rows(path,rows)
    assert not summarize([path])["gates"]["timings_complete"]


def test_no_sample_and_duplicate_rejected(tmp_path):
    path=write_rows(tmp_path/"log.jsonl",[])
    report=summarize([path])
    assert report["average_ms"] is None and not report["passed"]
    write_rows(path,[sample(1),sample(1)])
    with pytest.raises(ValueError,match="重複"):
        summarize([path])


def test_pre_admitted_capture_failure_is_counted(tmp_path):
    clock=Clock()
    t=ActionTelemetry(tmp_path,clock,"live_autonomous",trials=[{"logical_action":"summon","category":"SPECIAL_SUMMON"}])
    class Empty:
        def read(self): return None
    assert MeasuredCapture(Empty(),t).read() is None
    clock.value=3
    t.close("time_limit")
    assert len(t.records)==1 and t.records[0]["steps_count"]==0
    assert t.records[0]["total_ms"]==2000 and t.records[0]["admission"]=="scheduled_trial"
    report=summarize([tmp_path/"logical-actions.jsonl"])
    assert report["samples"]==1 and report["success_rate"]==0


def test_candidate_only_logs_never_pass_baseline_gate(tmp_path):
    rows=[{**sample(i),"admission":"candidate_observed"} for i in range(100)]
    report=summarize([write_rows(tmp_path/"rows.jsonl",rows)])
    assert not report["gates"]["pre_admitted_trials"]


def test_unsent_replanning_not_input_retry(tmp_path):
    t=ActionTelemetry(tmp_path,Clock())
    r=rule(start=True)
    begin(t,1,r);begin(t,1.1,r);t.input_result(True,(1,2))
    assert not t.current_step["retry"]
    begin(t,1.2,r)
    assert not t.current_step["retry"]
    t.input_result(True,(1,2))
    assert t.current_step["retry"]


def test_failed_trial_without_candidate_keeps_fallback_flag(tmp_path):
    clock=Clock()
    t=ActionTelemetry(tmp_path,clock,"synthetic",trials=[{"logical_action":"summon","category":"SPECIAL_SUMMON"}])
    t.admit(clock());t.event("fallback");clock.value=2;t.close("time_limit")
    assert t.records[0]["fallback_used"] and t.records[0]["steps_count"]==0

# 目的判定のみを検証する合成状態。実機認識精度の主張には使わない。
def zone_case(tmp_path, *, occupancy='empty', selected='12950', target='self.monster_2', sent=True, final_id='12950', selection_at=None, selection_source='template:fact.selection.card_id'):
    from master_duel_advisor.strategy_rules import LogicalZoneTransition
    from master_duel_advisor.models import CardIdentity, PlayerState
    spec=LogicalZoneTransition(zone='monster_2',card_id='12950',selected_card_fact='selection.card_id',placement_region='action.place')
    r=rule(start=True,logical_zone_transition=spec)
    t=ActionTelemetry(tmp_path,Clock(),'synthetic')
    def zstate(at, occ, cid=None, selection=None):
        facts={}
        if occ is not None:facts['zone.self.monster_2.occupancy']=Observation(value=occ,confidence=1,observed_at=at,source='template:fact.zone.self.monster_2.occupancy')
        if selection is not None:facts['selection.card_id']=Observation(value=selection,confidence=1,observed_at=at if selection_at is None else selection_at,source=selection_source)
        zones={'monster_2':Observation(value=CardIdentity(card_id=cid),confidence=1,observed_at=at,source='card:self.zones.monster_2')} if cid else {}
        return state(at).model_copy(update={'facts':facts,'self':PlayerState(zones=zones)})
    def step(at,r,s,region='action.open',target=None):
        a=Action(type='CONFIRM',source_region=region,target=target,confidence=1,observed_at=at)
        t.begin_step(a,r,s,Frame(np.zeros((2,2,3),np.uint8),at,int(at*1000),capture_start=at-.1,capture_end=at),{})
    first=zstate(1,occupancy);step(1,r,first);t.input_result(True,(1,1))
    final_rule=rule(end=True,logical_zone_transition=spec)
    middle=zstate(2,'empty',selection=selected);step(2,final_rule,middle,'action.place',target);t.input_result(sent,(2,2))
    final=zstate(3,'occupied',final_id)
    return t,final_rule,final,zstate


def test_zone_goal_positive_and_chain_does_not_delay_completion(tmp_path):
    t,r,s,_=zone_case(tmp_path)
    s=s.model_copy(update={'prompt':Observation(value='chain.select',confidence=1,observed_at=3)})
    assert t.goal_confirmed(r,s)
    t.complete_step('changed',r,s,at=3)
    assert t.records[0]['result']=='success'


@pytest.mark.parametrize('change',[{'occupancy':None},{'occupancy':'occupied'},{'selected':'wrong'}, {'target':'self.monster_3'},{'sent':False},{'sent':None},{'final_id':'wrong'}])
def test_zone_goal_requires_each_independent_evidence(tmp_path,change):
    t,r,s,_=zone_case(tmp_path,**change)
    assert not t.goal_confirmed(r,s)


def acceptance_case(tmp_path, slots=1):
    """合成検証専用manifest。本物のレビュー/性能資料として保存しない。"""
    manifest = {"schema": "acceptance-cohort-v1", "cohort_id": "fixture-only", "source_sha256": "fixture-source",
                "environment": {"python": "fixture", "platform": "fixture"}, "runs": []}
    logs, metadata_list = [], []
    for index in range(slots):
        count = 100 // slots
        metadata = {"run_id": f"run-{index}", "run_purpose": "acceptance", "cohort_id": "fixture-only",
                    "cohort_slot": f"slot-{index}", "source_sha256": "fixture-source", "python": "fixture", "platform": "fixture",
                    "provenance_frozen_before_capture": True,
                    "data_integrity": True,
                    "registered_trials": [{"logical_action": "summon", "category": "SPECIAL_SUMMON"}] * count}
        for key in FINGERPRINT_FIELDS:
            metadata[key] = {"fixture": index}  # カテゴリ別の校正/ルート差を事前登録できる。
            if key == "execution_conditions":
                metadata[key]["runtime"] = {"offline_cards": True, "data_files": {"database": {"path": "fixture-only", "sha256": "fixture-only"}}}
            metadata[key + "_sha256"] = value_hash(metadata[key])
        manifest["runs"].append({"slot_id": f"slot-{index}", "trials": ["summon"] * count,
                                 "expected_fingerprint": {k + "_sha256": metadata[k + "_sha256"] for k in FINGERPRINT_FIELDS}})
        rows = [{**sample(index * count + i), "run_id": metadata["run_id"], "logical_action": "summon",
                 **{k: metadata[k] for k in ("run_purpose", "cohort_id", "cohort_slot")}} for i in range(count)]
        run = tmp_path / str(index); run.mkdir()
        logs.append(write_rows(run / "logical-actions.jsonl", rows))
        metadata_list.append(metadata)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    reviews = []
    for path, metadata in zip(logs, metadata_list):
        metadata["cohort_manifest_sha256"] = value_hash(manifest)
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for row in rows:
            row["cohort_manifest_sha256"] = value_hash(manifest)
            reviews.extend({"step_id": s["step_id"], "misclick": False, "evidence": "synthetic-fixture", "reviewer": "fixture"} for s in row["steps"])
        write_rows(path, rows)
        (path.parent / "run-metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    rp = write_rows(tmp_path / "reviews.jsonl", reviews)
    def report():
        return summarize(logs, required_categories=["SPECIAL_SUMMON"], required_step_types=[], reviews=[rp], cohort_manifest=manifest_path)
    return logs, metadata_list, manifest_path, rp, report


def test_manifest_registered_category_variants_pass_synthetic_gate(tmp_path):
    _, _, _, _, report = acceptance_case(tmp_path, slots=2)
    assert report()["passed"]


@pytest.mark.parametrize("field", ["source_sha256", "python", "platform", "calibration_sha256", "strategy_sha256", "template_assets_sha256", "execution_conditions_sha256", "cohort_id", "run_purpose", "cohort_manifest_sha256"])
def test_mixed_or_unknown_provenance_cannot_pass(tmp_path, field):
    logs, metadata, _, _, report = acceptance_case(tmp_path)
    metadata[0][field] = "changed"
    (logs[0].parent / "run-metadata.json").write_text(json.dumps(metadata[0]), encoding="utf-8")
    assert not report()["gates"]["acceptance_cohort_integrity"]


@pytest.mark.parametrize("change", ["pilot", "missing_trial", "wrong_trial", "missing_metadata", "duplicate_slot", "changed_manifest"])
def test_trial_manifest_denominator_and_pilot_integrity(tmp_path, change):
    logs, metadata, mp, _, report = acceptance_case(tmp_path, slots=2)
    rows = [json.loads(line) for line in logs[0].read_text().splitlines()]
    if change == "pilot": rows[0]["run_purpose"] = "pilot"
    elif change == "missing_trial": rows.pop()
    elif change == "wrong_trial": rows[0]["logical_action"] = "other"
    elif change == "missing_metadata": (logs[0].parent / "run-metadata.json").unlink()
    elif change == "duplicate_slot":
        metadata[0]["cohort_slot"] = "slot-1"
        (logs[0].parent / "run-metadata.json").write_text(json.dumps(metadata[0]), encoding="utf-8")
    elif change == "changed_manifest":
        manifest = json.loads(mp.read_text()); manifest["cohort_id"] = "after-run"
        mp.write_text(json.dumps(manifest), encoding="utf-8")
    if change == "missing_trial":
        # 関連レビューも削除し、coverageではなくtrial欠落gateを検証。
        reviews = [{"step_id": s["step_id"], "misclick": False, "evidence": "fixture", "reviewer": "fixture"}
                   for path in logs for r in (rows if path == logs[0] else [json.loads(l) for l in path.read_text().splitlines()]) for s in r["steps"]]
        write_rows(tmp_path / "reviews.jsonl", reviews)
    write_rows(logs[0], rows)
    assert not report()["gates"]["acceptance_cohort_integrity"]


def test_unknown_input_included_in_review_denominator(tmp_path):
    logs, _, _, _, report = acceptance_case(tmp_path)
    rows = [json.loads(line) for line in logs[0].read_text().splitlines()]
    rows[0]["steps"][0]["input_sent"] = None; rows[0]["input_count"] = 1
    write_rows(logs[0], rows)
    result = report()
    assert result["input_count"] == 199 and result["misclick_denominator"] == 200
    assert result["unknown_input_count"] == 1 and result["misclick_rate"] == 0


def test_acceptance_start_rejects_unregistered_settings_before_capture(tmp_path):
    _, _, manifest, _, _ = acceptance_case(tmp_path)
    t = ActionTelemetry(tmp_path / "actual", mode="live_autonomous", trials=[{"logical_action": "summon"}],
                        run_purpose="acceptance", cohort_manifest=manifest, cohort_slot="slot-0")
    with pytest.raises(ValueError, match="本試験"):
        t.admit(1)
    assert not t.records and t.active is None


def test_capture_freezes_metadata_changes(tmp_path):
    t = ActionTelemetry(tmp_path)
    t.configure(calibration={"fixture": True}); t.admit(1)
    with pytest.raises(ValueError, match="設定変更"):
        t.configure(calibration={"changed": True})


def test_acceptance_start_snapshots_registered_manifest_before_capture(tmp_path):
    config = {key: {"fixture": "合成検証のみ"} for key in FINGERPRINT_FIELDS}
    import hashlib
    database = tmp_path / "fixture.db"; database.write_bytes(b"fixture-only")
    config["execution_conditions"] = {"runtime": {"offline_cards": True, "data_files": {
        "database": {"path": str(database), "sha256": hashlib.sha256(database.read_bytes()).hexdigest()}}}}
    trials = [{"logical_action": "summon", "category": "SPECIAL_SUMMON"}]
    reference = ActionTelemetry(tmp_path / "reference", trials=trials)
    reference.configure(**config)
    manifest = {"schema": "acceptance-cohort-v1", "cohort_id": "fixture", "source_sha256": reference.metadata["source_sha256"],
                "environment": {key: reference.metadata[key] for key in ("python", "platform")},
                "runs": [{"slot_id": "one", "trials": ["summon"],
                          "expected_fingerprint": {key + "_sha256": reference.metadata[key + "_sha256"] for key in FINGERPRINT_FIELDS}}]}
    mp = tmp_path / "manifest.json"; mp.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "accepted"
    t = ActionTelemetry(output, trials=trials, run_purpose="acceptance", cohort_manifest=mp, cohort_slot="one")
    t.configure(**config); t.freeze_provenance()
    assert json.loads((output / "cohort-manifest.json").read_text(encoding="utf-8")) == manifest
    assert not t.records and t.active is None  # capture開始より前に保存済み。
    t.admit(1)
    assert t.active["logical_action"] == "summon"
    duplicate = ActionTelemetry(output, trials=trials, run_purpose="acceptance", cohort_manifest=mp, cohort_slot="one")
    duplicate.configure(**config)
    with pytest.raises(FileExistsError): duplicate.freeze_provenance()
    t.assert_data_unchanged()
    database.write_bytes(b"changed-fixture-only")
    with pytest.raises(ValueError, match="ファイル変更"):
        t.assert_data_unchanged()
    assert t.metadata["data_integrity"] is False


def test_acceptance_cli_rejects_online_before_pipeline(tmp_path):
    from master_duel_advisor.cli import main
    # 存在しない校正でも、DB/外部接続を開く前にonlineを拒否。
    assert main(["agent-loop", "--run-purpose", "acceptance", "--calibration", str(tmp_path / "missing.json"),
                 "--database", str(tmp_path / "missing.db"), "--rect", "0,0,1280,720"]) == 2


@pytest.mark.parametrize('part',['empty_stale','empty_inferred','selection_stale','selection_inferred','occupied_stale','card_stale','same_sequence','no_selection','wrong_region'])
def test_zone_goal_rejects_stale_inferred_or_unlinked_evidence(tmp_path,part):
    t,r,s,_=zone_case(tmp_path,**({'selection_at':1} if part=='selection_stale' else {'selection_source':'inferred'} if part=='selection_inferred' else {}))
    if part.startswith('empty_'):
        ob=t.active['state_before']['facts']['zone.self.monster_2.occupancy']
        ob.update({'observed_at':0} if part.endswith('stale') else {'source':'inferred'})
    elif part.startswith('selection_'):
        assert t.active['steps'][-1]['selection_evidence'] is None
    elif part=='no_selection':
        t.active['steps'][-1]['selection_evidence']=None
    elif part=='occupied_stale':
        facts=dict(s.facts);key='zone.self.monster_2.occupancy';facts[key]=facts[key].model_copy(update={'observed_at':1});s=s.model_copy(update={'facts':facts})
    elif part=='card_stale':
        zones=dict(s.self.zones);zones['monster_2']=zones['monster_2'].model_copy(update={'observed_at':1});s=s.model_copy(update={'self':s.self.model_copy(update={'zones':zones})})
    elif part=='same_sequence':s=s.model_copy(update={'sequence':2000})
    elif part=='wrong_region':t.active['steps'][-1]['action']['source_region']='action.other'
    assert not t.goal_confirmed(r,s)

def test_zone_goal_scheduled_trial_preserves_first_empty_observation(tmp_path):
    from master_duel_advisor.strategy_rules import LogicalZoneTransition
    spec=LogicalZoneTransition(zone='monster_2',card_id='12950',selected_card_fact='selection.card_id',placement_region='action.place')
    reference,r,final,zstate=zone_case(tmp_path/'reference')
    t=ActionTelemetry(tmp_path/'scheduled',Clock(),'synthetic',trials=[{'logical_action':'summon','category':'NORMAL_SUMMON','count_fact':None,'zone_transition':spec.model_dump()}])
    frame=Frame(np.zeros((2,2,3),np.uint8),1,1000,capture_start=.9,capture_end=1)
    t.admit(.9);t.observe(frame,zstate(1,'empty'))
    t.active['steps']=reference.active['steps']
    assert t.goal_confirmed(r,final)
    t.active['state_before']['facts']={}
    # 後続のemptyを開始時空状態に代用しない。
    t.observe(Frame(frame.pixels,2,2000,capture_start=1.9,capture_end=2),zstate(2,'empty'))
    assert not t.goal_confirmed(r,final)


def test_zone_metadata_refuses_other_goal_and_opponent(tmp_path):
    from master_duel_advisor.strategy_rules import LogicalZoneTransition, StrategyRule
    from pydantic import ValidationError
    spec={'zone':'monster_2','card_id':'12950','selected_card_fact':'selection.card_id','placement_region':'action.place'}
    with pytest.raises(ValidationError):LogicalZoneTransition(**spec,side='opponent')
    base={'id':'normal','description':'test','type':'CONFIRM','source_region':'action.place','priority':1,'logical_action':'normal','logical_zone_transition':spec}
    for extra in ({'logical_action':None},{'logical_count_fact':'count.x'},{'logical_phase':'END'},{'logical_turn_advance':True}):
        with pytest.raises(ValidationError):StrategyRule(**(base|extra))

def test_zone_later_different_selection_invalidates_previous_placement(tmp_path):
    from copy import deepcopy
    t,r,s,_=zone_case(tmp_path)
    later=deepcopy(t.active['steps'][-1]);later['input_sent']=False
    later['before_sequence']=2500;later['action']['source_region']='action.select'
    later['selection_evidence']['value']='wrong';t.active['steps'].append(later)
    assert not t.goal_confirmed(r,s)
