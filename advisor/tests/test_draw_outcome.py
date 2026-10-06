"""既知Draw代替/旧Draw/意味境界。保存画像の通過を実機成功へ換算しません。"""
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import build_pipeline,close_pipeline
from master_duel_advisor.draw_outcome import DrawOverlayDetector,PARAMETERS,shape_score
from master_duel_advisor.image_io import read_image
from master_duel_advisor.models import Observation

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/solo-basic-calibration-v4"
RUN=ROOT/"artifacts/baseline-tester/SOLO_END_PILOT_v2_20261006/screenshots"
TRAIN=ROOT/"artifacts/baseline-tester/OPTIONAL_RESPONSE_TRAIN_v1_20261006"


def pipeline():
    return build_pipeline(BASE/"calibration.json",ROOT/"data/decks/thunder-dragon-review/cards.sqlite3",
        BASE/"solo-route.json",BASE/"ui-rules.json")


def test_known_failed_runtime_overlay_is_method_selection_not_actual_success():
    detector=DrawOverlayDetector(BASE/"draw-overlay.json");p=pipeline()
    try:
        for role,seq in [("last_recognized",19),("last_captured",20)]:
            path=RUN/f"verify-failure-0000-{role}-seq{seq}.png"
            side=json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            assert hashlib.sha256(path.read_bytes()).hexdigest()==side["image_sha256"]
            image=read_image(path);evidence=detector.detect(image)
            assert evidence.passed and evidence.word_score==1 and evidence.self_blue_ratio>.70
            state=p.perception.process(Frame(image,0,seq,capture_source="saved_image"))
            assert state.phase.value=="DRAW" and state.turn_player.value=="self" and state.prompt.value=="none"
            assert state.facts["response.modal_absent"].value=="true"
            assert state.facts["response.outcome.self_draw"].source=="draw_overlay:"+detector.sha256
            assert state.animation.value is not False
        assert detector.provenance()["binary_confidence"]=="predicate pass only, not probability"
    finally:close_pipeline(p)


def test_overlay_free_draw_twenty_remains_on_legacy_positive_route():
    p=pipeline()
    try:
        for path in (TRAIN/"end-response-after").glob("frame-*.png"):
            state=p.perception.process(Frame(read_image(path),0,1,capture_source="saved_image"))
            assert state.phase.value=="DRAW" and state.turn_player.value=="self"
            assert state.facts["response.outcome.self_draw"].source.startswith("template:")
    finally:close_pipeline(p)


def test_actual_other_large_phase_overlay_and_red_response_negatives():
    detector=DrawOverlayDetector(BASE/"draw-overlay.json")
    for name in ["frame-0441.png","frame-0443.png"]:
        evidence=detector.detect(read_image(ROOT/"artifacts/baseline-tester/MSS_END_LABELED_v4"/name))
        assert evidence.self_blue_ratio>=.15 and evidence.word_score<.90 and not evidence.passed
    for path in (TRAIN/"summon-response-after").glob("frame-*.png"):
        evidence=detector.detect(read_image(path))
        assert evidence.self_blue_ratio==0 and not evidence.passed


@pytest.mark.parametrize("case",["red_badge","no_blue","different_word","blank_word","no_modal_absent"])
def test_synthetic_word_blue_and_modal_evidence_are_independent(case):
    detector=DrawOverlayDetector(BASE/"draw-overlay.json")
    pixels=read_image(RUN/"verify-failure-0000-last_recognized-seq19.png").copy()
    if case=="red_badge":pixels[294:312,970:1002]=pixels[294:312,970:1002,::-1]
    elif case=="no_blue":pixels[294:312,970:1002]=0
    elif case=="different_word":pixels[337:388,416:871]=pixels[337:388,416:871][:,::-1]
    elif case=="blank_word":pixels[337:388,416:871]=0
    else:pixels[440:482,425:852]=0
    evidence=detector.detect(pixels)
    if case=="no_modal_absent":
        assert evidence.passed
        p=pipeline()
        try:
            state=p.perception.process(Frame(pixels,0,1,capture_source="saved_image"))
            assert state.facts["response.modal_absent"].value is None
            assert state.facts["response.outcome.self_draw"].value is None
        finally:close_pipeline(p)
    else:assert not evidence.passed


@pytest.mark.parametrize("case",["none","source_hash","config_hash","parameters","low_word","missing_blue","stale_diagnostic","same_sequence","no_actual_input","missing_modal"])
def test_goal_new_source_boundary_preserves_actual_input_and_fresh_sequence(tmp_path,case):
    from test_response_decline import response_case
    tel,rule,state=response_case(tmp_path)
    detector=DrawOverlayDetector(BASE/"draw-overlay.json")
    component=detector.provenance();tel.metadata["recognition_components"]["draw_overlay"]=component
    raw={"word_score":1.,"self_blue_ratio":.72,"config_sha256":detector.sha256}
    facts={**state.facts,"response.outcome.self_draw":Observation(value="true",confidence=1,
        source="draw_overlay:"+detector.sha256,observed_at=state.captured_at)}
    if case=="source_hash":facts["response.outcome.self_draw"]=facts["response.outcome.self_draw"].model_copy(update={"source":"draw_overlay:wrong"})
    elif case=="config_hash":raw["config_sha256"]="wrong"
    elif case=="parameters":component["parameters"]={**PARAMETERS,"word_score_min":.1}
    elif case=="low_word":raw["word_score"]=.899
    elif case=="missing_blue":raw["self_blue_ratio"]=0
    elif case=="same_sequence":state=state.model_copy(update={"sequence":tel.current_step["before_sequence"]})
    elif case=="no_actual_input":tel.current_step["input_sent"]=False
    elif case=="missing_modal":facts["response.modal_absent"]=Observation(observed_at=state.captured_at)
    facts["response.draw_overlay_diagnostic"]=Observation(value=json.dumps(raw),confidence=0,
        source="diagnostic:not_a_legal_fact",observed_at=state.captured_at-1 if case=="stale_diagnostic" else state.captured_at)
    state=state.model_copy(update={"facts":facts})
    assert tel.goal_confirmed(rule,state)==(case=="none")


def test_asset_mutation_and_wrong_native_shape_fail_closed(tmp_path):
    target=tmp_path/"assets";shutil.copytree(BASE,target);detector=DrawOverlayDetector(target/"draw-overlay.json")
    with pytest.raises(ValueError):detector.detect(np.zeros((752,1282,3),np.uint8))
    asset=target/"draw-overlay-method-selection-seq19.png";asset.write_bytes(asset.read_bytes()+b"changed")
    with pytest.raises(ValueError):detector.detect(np.zeros((720,1280,3),np.uint8))
    with pytest.raises(ValueError):DrawOverlayDetector(target/"draw-overlay.json")


def test_synthetic_shape_score_has_own_fixed_scale():
    detector=DrawOverlayDetector(BASE/"draw-overlay.json");proto=detector.prototype
    assert shape_score(proto,np.pad(proto[:,:-6],((0,0),(6,0))))<.90
    assert shape_score(proto,np.ones_like(proto))<.90
