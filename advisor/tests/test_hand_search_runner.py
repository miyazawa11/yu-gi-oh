"""実CLI構築＋hand単独guard。capture/controlはsyntheticで実機操作なし。"""
import importlib.util
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

from master_duel_advisor.agent_loop import AgentLoop,LoopLimits
from master_duel_advisor.capture import Frame,LiveCaptureSource
from master_duel_advisor.cli import build_pipeline,close_pipeline
from master_duel_advisor.image_io import read_image
from master_duel_advisor.models import Action,GameState
from master_duel_advisor.telemetry import load_trials

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/dragondark-hand-search-calibration-v3"
PREP=ROOT/"artifacts/baseline-tester/DRAGONDARK_PILOT_PREPARATION_v1_20261006/ready-effect-menu/frame-0000.png"
RECT=(100,200,1380,920)


def pipeline():
    return build_pipeline(BASE/"calibration.json",ROOT/"data/decks/thunder-dragon-review/cards.sqlite3",BASE/"solo-route.json",BASE/"ui-rules.json")


def helper(filename="preflight_solo_response.py"):
    spec=importlib.util.spec_from_file_location("hand_preflight_helper",ROOT/"scripts"/filename)
    module=importlib.util.module_from_spec(spec)
    sys.path.insert(0,str(ROOT/"scripts"))
    try:spec.loader.exec_module(module)
    finally:sys.path.pop(0)
    return module


class NoInputClicker:
    def __init__(self):
        self.points=[];self.checked=[]
        self.control=SimpleNamespace(validate_point=lambda *point:self.checked.append(point))
    def input_epoch(self):return 42
    def click(self,*point):raise AssertionError("接続testで実入力は禁止です")


@pytest.mark.parametrize("case",["native","saved","other_backend","wrong_rect"])
def test_hand_only_constructor_binds_native_capture_and_activity_guard(tmp_path,case):
    p=pipeline();clicker=NoInputClicker()
    # 真の型だけ合成。MSScamera/window APIは起動しません。
    capture=object.__new__(LiveCaptureSource)
    capture.rect=RECT;capture.backend="mss";capture.camera=None
    if case=="saved":capture=SimpleNamespace(rect=RECT,backend="mss")
    elif case=="other_backend":capture.backend="dxcam"
    elif case=="wrong_rect":capture.rect=(101,200,1381,920)
    p.perception.inspect_goal=None;p.perception.response_goals=()
    try:
        loop=AgentLoop(capture,p,p.perception.calibration,clicker,SimpleNamespace(stopped=lambda:False),tmp_path,RECT,
            LoopLimits(max_actions=3,max_retries=0,max_seconds=20,verify_seconds=8),telemetry_mode="live_autonomous")
        assert loop.guarded_scope
        assert loop.inspection_live_bound==(case=="native")
        assert (loop.capture.activity_probe is not None)==(case=="native")
        assert p.perception.inspect_client_rect==(RECT if case=="native" else None)
        if case!="native":
            at=1.;frame=Frame(read_image(PREP),at,0,capture_source="live_mss",capture_rect=RECT,input_epoch=42)
            action=Action(type="ACTIVATE",card_id="13906",confidence=1,source_region=p.perception.hand_goal.activate_region,observed_at=at)
            with pytest.raises(ValueError,match="実MSS"):
                loop._coordinates(action,frame.pixels.shape,frame=frame,state=GameState(sequence=0,captured_at=at))
    finally:close_pipeline(p)


def test_cli_pipeline_hand_trials_and_fresh_start_preflight_connection(tmp_path):
    p=pipeline();clicker=NoInputClicker()
    capture=object.__new__(LiveCaptureSource);capture.rect=RECT;capture.backend="mss";capture.camera=None
    try:
        trials=load_trials(BASE/"hand-search-trials.json",p.planner)
        assert len(trials)==1 and trials[0]["hand_search_confirmation"]==p.perception.hand_goal.model_dump(mode="json")
        loop=AgentLoop(capture,p,p.perception.calibration,clicker,SimpleNamespace(stopped=lambda:False),tmp_path,RECT,
            LoopLimits(max_actions=3,max_retries=0,max_seconds=20,verify_seconds=8),telemetry_mode="live_autonomous",benchmark_trials=trials)
        # 独立合成wrapperの時計。保存画像の元captured_atを書換える処理ではありません。
        frame=Frame(read_image(PREP),time.monotonic(),0,capture_source="live_mss",capture_rect=RECT,input_epoch=42)
        result=p.process(frame);state=GameState.model_validate(result["state"])
        action=Action.model_validate(result["recommendation"]["action"])
        assert action.type.value=="ACTIVATE" and action.hand_search_proof is not None
        h=helper();point=h.starting_point(loop,p,action,state,frame,"dragondark_hand_search")
        assert point==(783,724) and clicker.checked==[point]
        assert h.starting_point(loop,p,action,state,frame,"other_goal") is None
        loop.telemetry.admit(0.)
        assert loop.telemetry.active["hand_search_confirmation"]==trials[0]["hand_search_confirmation"]
        assert clicker.points==[]
    finally:close_pipeline(p)


@pytest.mark.parametrize("extra,expected",[([],3),(["--verify-seconds","8"],8)])
def test_cli_verify_timeout_is_explicit_and_preserves_old_default(extra,expected):
    from master_duel_advisor.cli import parser
    args=parser().parse_args(["agent-loop","--rect","100,200,1380,920",
        "--calibration",str(BASE/"calibration.json"),"--database","synthetic.sqlite3",*extra])
    assert args.verify_seconds==expected


def test_ready_hand6_full_pipeline_keeps_animation_unknown_with_receipted_inspect(tmp_path):
    p=pipeline()
    try:
        goal=p.perception.hand_goal;v=p.perception.hand_vision;at=time.monotonic()
        p.perception.inspect_client_rect=RECT
        v.episode={"action_id":"synthetic-full-pipeline","layout":"hand6-slot3","profile_sha256":v.sha256,
            "failed":None,"ready":True,"anchor":{"seq":45,"at":at-1.,"cid":"13906"},
            "handoff":{"seq":61,"at":at-.1,"bbox":[633,606,100,150]},"last_seq":61,"last_at":at-.1,"trace":[]}
        context={"action_id":"synthetic-full-pipeline","hand_search_confirmation":goal.model_dump(mode="json"),
            "steps":[{"input_sent":True,"before_sequence":9},
                {"input_sent":True,"before_sequence":20,"client_rect":list(RECT),"input_epoch":42}]}
        ready=ROOT/"artifacts/baseline-tester/DRAGONDARK_SEARCH_TRAIN_v1_20261006/post-search-hand-unselected/frame-0000.png"
        frame=Frame(read_image(ready),at,62,capture_source="live_mss",capture_rect=RECT,input_epoch=42)
        state=p.perception.process(frame,hand_episode_context=context)
        assert state.animation.value is None  # 局所形状からglobal idleを生成しません。
        assert state.prompt.value=="hand.dragondark.result_ready"
        rules=[r for r in p.planner.book.rules if r.logical_hand_search_confirmation]
        p.planner.last_completed=rules[1].id
        choices=p.planner.filter_actions(state,state.visible_actions)
        rec=p.ui_policy.decide(state,tuple(choices))
        assert rec and rec.action and rec.action.type.value=="SELECT_CARD"
        assert rec.action.hand_search_proof.point==tuple(v.episode["current_ready_geometry"]["point"])
    finally:close_pipeline(p)


def test_fixed_pilot_limits_match_cli_numeric_serialization():
    from dataclasses import asdict
    from master_duel_advisor.cli import parser
    from master_duel_advisor.telemetry import value_hash
    args=parser().parse_args(["agent-loop","--rect","100,200,1380,920","--calibration",str(BASE/"calibration.json"),
        "--database","synthetic.sqlite3","--max-seconds","20","--max-actions","3","--max-retries","0",
        "--max-same-action","1","--verify-seconds","8","--verify-poll-seconds","0.05","--settle-seconds","0"])
    limits=LoopLimits(max_seconds=args.max_seconds,max_actions=args.max_actions,max_retries=args.max_retries,
        max_same_action=args.max_same_action,verify_seconds=args.verify_seconds,verify_poll_seconds=args.verify_poll_seconds,
        settle_seconds=args.settle_seconds)
    assert value_hash(asdict(limits))==value_hash(asdict(helper("freeze_hand_search.py").PILOT_LIMITS))
