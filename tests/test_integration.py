import json
import sys
import time
from types import SimpleNamespace
import urllib.request

import cv2
import numpy as np
import pytest

from master_duel_advisor.advisor import SnapshotStore, start_server
from master_duel_advisor.benchmark import benchmark
from master_duel_advisor.capture import Frame, LiveCaptureSource, VideoCaptureSource
from master_duel_advisor.cli import main
from master_duel_advisor.evaluation import evaluate
from master_duel_advisor.pipeline import FrameGate
from master_duel_advisor.regions import Calibration, Rect, Region


def test_synthetic_evaluation_cannot_pass_real_gate(pipeline,assets,tmp_path):
    report=evaluate(assets["dataset"],pipeline,tmp_path/"results.json")
    assert report["sample_count"]==4
    assert report["game_state_exact_accuracy"]==1
    assert report["action_exact_accuracy"]==1
    assert report["recommendation_exact_accuracy"]==1
    assert report["fields"]["phase"]["precision"]==1
    assert not report["real_perception_gate_passed"]
    assert report["errors"]==[]
    assert json.loads((tmp_path/"results.json").read_text())["sample_count"]==4


def test_wrong_ground_truth_is_failure_and_exit_code(assets,tmp_path):
    dataset=json.loads(assets["dataset"].read_text())
    dataset["samples"][0]["expected"]["self.lp"]=100
    assets["dataset"].write_text(json.dumps(dataset))
    assert main(["evaluate","--dataset",str(assets["dataset"]),"--calibration",str(assets["calibration"]),"--database",str(assets["database"]),"--output",str(tmp_path/"bad.json")])==1
    report=json.loads((tmp_path/"bad.json").read_text())
    assert report["fields"]["self.lp"]["fn"]==1
    assert report["fields"]["self.lp"]["fp"]==1


def test_empty_dataset_never_validates(pipeline,tmp_path):
    path=tmp_path/"empty.json"
    path.write_text('{"kind":"real_game","samples":[]}')
    with pytest.raises(ValueError,match="1件以上"):
        evaluate(path,pipeline,tmp_path/"out.json")


def test_small_relabelled_dataset_cannot_pass_gate(pipeline,assets,tmp_path):
    data=json.loads(assets["dataset"].read_text())
    data["kind"]="real_game"
    assets["dataset"].write_text(json.dumps(data))
    assert not evaluate(assets["dataset"],pipeline,tmp_path/"out.json")["real_perception_gate_passed"]


def test_video_uses_same_pipeline_and_media_times(pipeline,assets):
    source=VideoCaptureSource(assets["video"])
    gate=FrameGate()
    results=[]
    media_times=[]
    try:
        while (frame:=source.read()) is not None:
            media_times.append(frame.media_time)
            if gate.accept(frame):
                results.append(pipeline.process(frame))
    finally:
        source.close()
    assert len(media_times)==12
    assert media_times[-1]==pytest.approx(1.1)
    assert len(results)==4
    assert results[0]["recommendation"]["action"]["type"]=="NORMAL_SUMMON"
    assert results[1]["recommendation"]["action"]["type"]=="ATTACK"
    assert results[2]["recommendation"]["action"] is None
    assert results[3]["recommendation"]["action"]["type"]=="ACTIVATE"
    assert results[1]["events"]


def test_changed_aspect_fails_closed(pipeline):
    result=pipeline.process(Frame(np.zeros((480,640,3),np.uint8),time.monotonic(),1))
    assert result["error"] and "縦横比" in result["error"]
    assert result["recommendation"]["action"] is None


def test_frame_gate_refresh_and_small_changes():
    gate=FrameGate()
    black=np.zeros((360,640,3),np.uint8)
    assert gate.accept(Frame(black,10,0))
    assert not gate.accept(Frame(black,10.1,1))
    assert gate.accept(Frame(black,11.1,2))
    assert gate.accept(Frame(np.full_like(black,255),11.2,3))


def test_region_gate_does_not_lose_small_ui_changes():
    black=np.zeros((360,640,3),np.uint8)
    changed=black.copy()
    changed[180:187,320:332]=255
    calibration=Calibration(name="small-action",regions={"action.primary":Region(rect=Rect(x=.5,y=.5,width=.02,height=.02),kind="unobserved")})
    global_gate=FrameGate()
    region_gate=FrameGate(calibration=calibration)
    assert global_gate.accept(Frame(black,10,0))
    assert region_gate.accept(Frame(black,10,0))
    assert not global_gate.accept(Frame(changed,10.1,1))
    assert region_gate.accept(Frame(changed,10.1,1))


def test_http_ui_functional_request_and_stale_abstention(pipeline,assets):
    store=SnapshotStore(max_age=.02)
    image=cv2.imread(str(assets["calibration"].parent/"frame_0.png"))
    store.update(pipeline.process(Frame(image,time.monotonic(),0)))
    server,thread=start_server(store,0)
    try:
        address=f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(address) as response:
            assert "推奨行動" in response.read().decode("utf-8")
        # 時間経過に依存せず、管理された更新時刻で検証します。
        store.updated=time.monotonic()-2
        with urllib.request.urlopen(address+"/state") as response:
            state=json.load(response)
        assert state["state"]["self"]["lp"]["value"]==8000
        assert state["recommendation"]["recognition_status"]=="stale"
        assert state["recommendation"]["action"] is None
        assert "新しい画面" in state["recommendation"]["reason"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_replay_benchmark_does_not_claim_live_drop_or_gpu(assets):
    result=benchmark(VideoCaptureSource(assets["video"]),5,30,False)
    assert result["frames_received"]==12
    assert result["unique_frames"]==4
    assert result["gpu_percent"] is None
    assert result["actual_frame_drop_rate"] is None
    assert result["estimated_scheduled_sample_miss_rate"] is None
    assert result["mode"]=="offline_replay"


@pytest.mark.skipif(sys.platform=="win32",reason="Windows 以外での実行制限を確認します")
def test_linux_live_capture_explicit_blocker():
    with pytest.raises(RuntimeError,match="Windows"):
        LiveCaptureSource("dxcam",(0,0,1920,1080))


def test_run_command_persists_current_outputs(assets,tmp_path):
    output=tmp_path/"run"
    assert main(["run","--video",str(assets["video"]),"--calibration",str(assets["calibration"]),"--database",str(assets["database"]),"--output",str(output)])==0
    summary=json.loads((output/"run.json").read_text())
    # 圧縮ノイズによる追加処理を許容し、全場面を処理して半分以上の画像を省略します。
    assert 4 <= summary["processed"] <= summary["captured"]//2
    assert json.loads((output/"latest.json").read_text())["state"]["sequence"]==9
    assert (output/"events.jsonl").read_text()


def test_loop_replay_resets_history_and_keeps_sequence(assets,tmp_path):
    output=tmp_path/"loop"
    assert main(["run","--video",str(assets["video"]),"--calibration",str(assets["calibration"]),"--database",str(assets["database"]),"--output",str(output),"--loop","--max-frames","13"])==0
    snapshot=json.loads((output/"latest.json").read_text())
    assert snapshot["state"]["sequence"]==12
    assert snapshot["state"]["media_time"]==0
    assert snapshot["events"]==[]


def test_dxcam_polls_without_indefinite_wait(monkeypatch):
    calls=[]
    camera=SimpleNamespace(grab=lambda region:(calls.append(region) or np.zeros((10,20,3),np.uint8)),release=lambda:calls.append("release"))
    monkeypatch.setattr(sys,"platform","win32")
    monkeypatch.setitem(sys.modules,"dxcam",SimpleNamespace(create=lambda output_color:camera))
    source=LiveCaptureSource("dxcam",(0,0,20,10))
    try:
        frame=source.read()
        assert frame.pixels.shape==(10,20,3)
        assert calls==[(0,0,20,10)]
    finally:
        source.close()
    assert calls[-1]=="release"


def test_dxcam_no_new_frame_returns_without_wait(monkeypatch):
    camera=SimpleNamespace(grab=lambda region:None,release=lambda:None)
    monkeypatch.setattr(sys,"platform","win32")
    monkeypatch.setitem(sys.modules,"dxcam",SimpleNamespace(create=lambda output_color:camera))
    source=LiveCaptureSource("dxcam",(0,0,20,10))
    try:
        assert source.read() is None
    finally:
        source.close()
