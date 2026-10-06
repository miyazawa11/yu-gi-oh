"""timeout証跡を実取得sequenceへ結合し、合成資料を実機成功に数えません。"""
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from master_duel_advisor.agent_loop import LoopLimits
from master_duel_advisor.capture import Frame
from master_duel_advisor.models import GameState


def test_outer_time_limit_saves_last_actual_runtime_without_extra_read(tmp_path):
    """合成clock/capture。最後のabstain画面を保全し、後刻captureを代用しません。"""
    from test_agent_loop import setup
    loop,clicks,_=setup(tmp_path);elapsed=[1.]
    loop.clock=lambda:elapsed[0];loop.sleep=lambda seconds:elapsed.__setitem__(0,elapsed[0]+seconds)
    loop.limits=LoopLimits(max_seconds=.1,verify_poll_seconds=.05)
    loop.inspection_goal=SimpleNamespace(zone="monster_2")
    frames=[Frame(np.full((100,200,3),(n-9)*40,np.uint8),1+(n-10)*.05,n,
        capture_source="live_mss",capture_rect=loop.screen_rect,input_epoch=7) for n in [10,11]]
    seen=[]
    def read():
        seen.append(len(seen));return frames[len(seen)-1]
    loop.capture.source.read=read
    def process(frame,**kwargs):
        return {"state":GameState(sequence=frame.sequence,captured_at=frame.captured_at).model_dump(mode="json"),
            "recommendation":{"action":None,"confidence":0,"reason":"synthetic-abstain"}}
    loop.pipeline.process=process
    summary=loop.run()
    assert summary["status"]=="time_limit" and seen==[0,1] and clicks.points==[]
    reports=list((tmp_path/"screenshots").glob("verify-failure-*-run_endpoint-seq11.json"));assert len(reports)==1
    report=json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["reason"]=="time_limit" and report["sequence"]==report["state"]["sequence"]==11
    assert report["captured_at_monotonic"]==1.05
    from pathlib import Path
    assert report["image_sha256"]==hashlib.sha256(Path(report["image"]).read_bytes()).hexdigest()


def test_runtime_last_capture_and_last_recognized_have_distinct_original_clocks(tmp_path):
    from test_agent_loop import setup
    loop,_,_=setup(tmp_path)
    first=Frame(np.zeros((100,200,3),np.uint8),1.,10)
    last=replace(first,pixels=np.full((100,200,3),80,np.uint8),captured_at=1.2,sequence=12)
    state=GameState(sequence=10,captured_at=1.)
    loop._remember_runtime(first,state);loop._remember_runtime(last)
    loop._save_verification_failure(loop.last_runtime_frame,loop.last_runtime_state,
        loop.last_runtime_recognized,"time_limit",endpoint=True)
    reports=[json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path/"screenshots").glob("*.json")]
    byrole={r["role"]:r for r in reports}
    assert byrole["run_endpoint"]["sequence"]==12 and byrole["run_endpoint"]["state"] is None
    assert byrole["run_last_recognized"]["sequence"]==byrole["run_last_recognized"]["state"]["sequence"]==10
    assert byrole["run_endpoint"]["captured_at_monotonic"]==1.2
    assert byrole["run_last_recognized"]["captured_at_monotonic"]==1.


@pytest.mark.parametrize('timeout_on_second',[False,True])
def test_verify_timeout_preserves_last_actual_frame_and_recognized_state(tmp_path,timeout_on_second):
    from test_agent_loop import setup
    loop,_,_=setup(tmp_path)
    elapsed=[1.0];loop.clock=lambda:elapsed[0];loop.sleep=lambda seconds:elapsed.__setitem__(0,elapsed[0]+seconds)
    loop.limits=LoopLimits(verify_seconds=.2,verify_poll_seconds=.05)
    loop.inspection_goal=SimpleNamespace(zone='monster_2')
    loop.current_action=loop.pipeline.action;loop.current_input_epoch=7
    loop.clicker.input_epoch=lambda:7;loop.telemetry.current_step={}
    loop.telemetry.mode='synthetic'
    first=Frame(np.full((100,200,3),50,np.uint8),1.05,1,capture_source='live_mss',capture_rect=loop.screen_rect,input_epoch=7)
    second=replace(first,pixels=np.full((100,200,3),80,np.uint8),captured_at=1.1,sequence=2)
    loop.capture.source.frames=iter([first,second])
    def recognize(frame):
        if timeout_on_second and frame.sequence==2:raise TimeoutError('synthetic-timeout')
        return GameState(sequence=frame.sequence,captured_at=frame.captured_at)
    loop.pipeline.perception.process=recognize
    loop.verification.expected=lambda *args:False
    after,state,status=loop._verify(Frame(np.zeros((100,200,3),np.uint8),1,0),GameState(sequence=0,captured_at=1))
    assert status=='unchanged' and after.sequence==2
    assert (state is None) if timeout_on_second else (state.sequence==2)
    files=list((tmp_path/'screenshots').glob('verify-failure-*-last_captured-*.json'))
    assert len(files)==1
    report=json.loads(files[0].read_text(encoding='utf-8'))
    assert report['sequence']==2 and report['captured_at_monotonic']==1.1
    assert report['telemetry_mode']=='synthetic'
    assert report['image_sha256']==hashlib.sha256(__import__('pathlib').Path(report['image']).read_bytes()).hexdigest()
    assert report['state'] is None if timeout_on_second else report['state']['sequence']==2
    previous=list((tmp_path/'screenshots').glob('verify-failure-*-last_recognized-*.json'))
    assert len(previous)==(1 if timeout_on_second else 0)
    if previous:
        prior=json.loads(previous[0].read_text(encoding='utf-8'))
        assert prior['sequence']==prior['state']['sequence']==1


def test_matcher_raw_failure_diagnostics_are_separate_from_adoption():
    from pathlib import Path
    from master_duel_advisor.cli import build_pipeline, close_pipeline
    from master_duel_advisor.image_io import read_image
    root=Path(__file__).resolve().parents[1];base=root/'artifacts/ash-normal-inspect-calibration-v2'
    pipeline=build_pipeline(base/'calibration.json',root/'data/decks/thunder-dragon-review/cards.sqlite3',base/'normal-route.json')
    image=read_image(root/'artifacts/baseline-tester/ASH_INSPECT_PILOT_v2_20261006/failure-current-mss/frame.png')
    name='fact.zone.self.monster_2.occupancy';crop=pipeline.perception.calibration.crop_regions(image)[name]
    matcher=pipeline.perception.matchers[name]
    assert .94 < matcher.diagnostic_scores(crop)['occupied'] < .95
    assert matcher.match(crop)==(None,0)
    close_pipeline(pipeline)


def test_hand_first_permanent_tracking_failure_saves_that_frame_and_previous_without_more_reads(tmp_path):
    """合成capture/receipt。後刻画面や取得時計を失敗瞬間へ代用しません。"""
    from test_agent_loop import setup
    from master_duel_advisor.perception import Perception
    from master_duel_advisor.strategy_rules import LogicalHandSearchConfirmation
    loop,_,_=setup(tmp_path);elapsed=[1.]
    loop.clock=lambda:elapsed[0];loop.sleep=lambda seconds:elapsed.__setitem__(0,elapsed[0]+seconds)
    loop.limits=LoopLimits(verify_seconds=8,verify_poll_seconds=.05)
    goal=LogicalHandSearchConfirmation();spec=goal.model_dump(mode="json")
    rule=SimpleNamespace(logical_hand_search_confirmation=goal,logical_response_decline=None,logical_end=False,
        expected_facts={goal.result_ready_fact:"true"},expected_prompts=[])
    p=object.__new__(Perception);p.hand_goal=goal;p.response_goals=();p.stage_spans=[];p.matchers={}
    loop.pipeline.perception=p;loop.pipeline.planner=SimpleNamespace(rule_for=lambda a:rule)
    loop.current_action=loop.pipeline.action;loop.current_input_epoch=7;loop.clicker.input_epoch=lambda:7
    loop.telemetry.current_step={};loop.telemetry.active={"hand_search_confirmation":spec,"action_id":"synthetic-failure"}
    loop.telemetry.hand_step_confirmed=lambda *args:False
    loop.telemetry.mode="synthetic"
    loop.screen_rect=(-1920,785,-640,1505)
    frames=[Frame(np.full((720,1280,3),n*40,np.uint8),1+n*.05,n,capture_source="live_mss",capture_rect=loop.screen_rect,input_epoch=7) for n in [1,2,3]]
    loop.capture.source.frames=iter(frames);seen=[]
    def recognize(frame,**kwargs):
        seen.append(frame.sequence)
        p.hand_episode={"action_id":"synthetic-failure","failed":"track_points_under6" if frame.sequence==2 else None,"trace":[{"seq":frame.sequence}]}
        return GameState(sequence=frame.sequence,captured_at=frame.captured_at)
    p.process=recognize
    after,state,status=loop._verify(Frame(np.zeros((720,1280,3),np.uint8),1,0),GameState(sequence=0,captured_at=1))
    assert status=="unchanged" and after.sequence==state.sequence==2 and seen==[1,2]
    files=list((tmp_path/"screenshots").glob("verify-failure-*-last_captured-*.json"));assert len(files)==1
    report=json.loads(files[0].read_text(encoding="utf-8"))
    assert report["sequence"]==2 and report["captured_at_monotonic"]==1.1
    assert report["reason"]=="hand_episode_failed:track_points_under6"
    assert report["hand_episode"]["failed"]=="track_points_under6"
    from pathlib import Path
    assert report["image_sha256"]==hashlib.sha256(Path(report["image"]).read_bytes()).hexdigest()
    prior=list((tmp_path/"screenshots").glob("verify-failure-*-before_hand_failure-*.json"));assert len(prior)==1
    previous=json.loads(prior[0].read_text(encoding="utf-8"))
    assert previous["sequence"]==previous["state"]["sequence"]==1 and previous["captured_at_monotonic"]==1.05
    assert any(e["status"]=="hand_episode_failed" and e["failure_category"]=="Recognition failure" for e in loop.telemetry.events)
