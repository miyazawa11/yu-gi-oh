import json
import shutil
import time

import cv2
import numpy as np
import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.cards import CardDatabase
from master_duel_advisor.perception import Perception, TemplateMatcher, TesseractOCR
from master_duel_advisor.regions import Exemplar, Rect, Region, load_calibration


def test_actual_templates_and_unknown(pipeline, assets):
    positive = cv2.imread(str(assets["calibration"].parent/"frame_0.png"))
    state = pipeline.perception.process(Frame(positive,time.monotonic(),0))
    assert state.self.lp.value == 8000
    assert state.self.zones["monster_1"].value.card_id == "demo-alpha"
    negative = cv2.imread(str(assets["calibration"].parent/"frame_2.png"))
    state = pipeline.perception.process(Frame(negative,time.monotonic(),1))
    assert state.self.lp.value is None
    assert state.self.zones["monster_1"].value is None
    assert state.visible_actions == []


def test_duplicate_exemplars_same_label_not_ambiguity(assets):
    calibration = load_calibration(assets["calibration"])
    region = calibration.regions["phase"]
    positive = region.exemplars[0]
    duplicate = region.model_copy(update={"exemplars":[positive,positive]})
    crop = cv2.imread(str(assets["calibration"].parent/positive.image))
    assert TemplateMatcher(duplicate, assets["calibration"].parent).match(crop)[0] == positive.label
    ambiguous = region.model_copy(update={"exemplars":[positive,Exemplar(label="BATTLE",image=positive.image)]})
    assert TemplateMatcher(ambiguous, assets["calibration"].parent).match(crop) == (None,0)


def test_template_asset_escape_rejected(assets):
    region = Region(rect=Rect(x=0,y=0,width=1,height=1),kind="template",exemplars=[Exemplar(label="MAIN1",image="../outside.png")])
    with pytest.raises(ValueError,match="校正ファイル"):
        TemplateMatcher(region,assets["calibration"].parent)


@pytest.mark.parametrize("field,label", [("phase","imaginary"),("turn_player","hidden"),("turn","-1"),("self.hand_count","100"),("action.primary","EXECUTE")])
def test_bad_calibration_semantics_rejected(assets,field,label):
    calibration = load_calibration(assets["calibration"])
    region = calibration.regions[field]
    changed = region.model_copy(update={"exemplars":[Exemplar(label=label,image=region.exemplars[0].image)]})
    calibration = calibration.model_copy(update={"regions":{**calibration.regions,field:changed}})
    db = CardDatabase()
    try:
        with pytest.raises(ValueError):
            Perception(calibration,assets["calibration"].parent,db)
    finally:
        db.close()


def test_unresolved_card_database_never_invents_identity(assets):
    db = CardDatabase()
    try:
        p = Perception(load_calibration(assets["calibration"]),assets["calibration"].parent,db)
        image = cv2.imread(str(assets["calibration"].parent/"frame_0.png"))
        assert p.process(Frame(image,time.monotonic(),0)).self.zones["monster_1"].value is None
    finally:
        db.close()


def test_missing_tesseract_returns_unknown():
    assert TesseractOCR("nonexistent-ocr-tool").read(np.zeros((60,200,3),np.uint8),999999) == (None,0)


@pytest.mark.skipif(shutil.which("tesseract") is None,reason="任意のローカル OCR ツールが未導入です")
@pytest.mark.parametrize("value",[8000,5200,999999])
def test_real_ocr_regression_no_forced_upscale(value):
    image=np.full((75,300,3),255,np.uint8)
    cv2.putText(image,str(value),(15,55),cv2.FONT_HERSHEY_SIMPLEX,1.6,(0,0,0),3,cv2.LINE_AA)
    recognized,confidence=TesseractOCR().read(image,999999)
    assert recognized == value
    assert confidence >= .9


def test_ocr_disagreement_abstains(monkeypatch):
    ocr = TesseractOCR()
    ocr.command = "test"
    outputs = iter([(5200,.99),(9200,.99)])
    monkeypatch.setattr(ocr,"_read_rendering",lambda rendering,maximum:next(outputs))
    assert ocr.read(np.full((80,200,3),255,np.uint8),999999) == (None,0)
