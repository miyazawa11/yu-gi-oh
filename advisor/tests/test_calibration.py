import cv2
import numpy as np
import pytest

from master_duel_advisor.calibration import calibrate_region
from master_duel_advisor.regions import Rect, load_calibration
from master_duel_advisor.image_io import write_image


def test_calibration_appends_exemplars_preserving_labels(tmp_path):
    screenshot=tmp_path/"frame.png"
    write_image(screenshot,np.full((360,640,3),120,np.uint8))
    path=tmp_path/"layout.json"
    rect=Rect(x=.5,y=.5,width=.1,height=.1)
    calibrate_region(path,screenshot,"phase","template",rect,"MAIN1")
    calibrate_region(path,screenshot,"phase","template",rect,"BATTLE")
    regions=load_calibration(path).regions
    assert [e.label for e in regions["phase"].exemplars]==["MAIN1","BATTLE"]
    assert all((path.parent/e.image).exists() for e in regions["phase"].exemplars)
    with pytest.raises(ValueError,match="座標"):
        calibrate_region(path,screenshot,"phase","template",Rect(x=0,y=0,width=.1,height=.1),"END")
    assert len(load_calibration(path).regions["phase"].exemplars)==2


def test_calibration_requires_label_and_correct_aspect(tmp_path):
    screenshot=tmp_path/"frame.png"
    write_image(screenshot,np.zeros((480,640,3),np.uint8))
    path=tmp_path/"layout.json"
    rect=Rect(x=0,y=0,width=.1,height=.1)
    with pytest.raises(ValueError,match="ラベル"):
        calibrate_region(path,screenshot,"phase","template",rect)
    with pytest.raises(ValueError,match="縦横比"):
        calibrate_region(path,screenshot,"self.lp","number",rect)
    assert not path.exists()
