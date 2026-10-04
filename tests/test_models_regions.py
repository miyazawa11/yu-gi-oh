import numpy as np
import pytest
from pydantic import ValidationError

from master_duel_advisor.models import GameState, Observation
from master_duel_advisor.regions import Calibration, Rect, Region


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_confidence_rejected(value):
    with pytest.raises(ValidationError):
        Observation(value=8000, confidence=value)


def test_unknown_is_not_zero_or_empty():
    assert Observation[int]().value is None
    assert Observation(value=0, confidence=1).value == 0
    assert GameState(sequence=0, captured_at=0).self.zones == {}
    with pytest.raises(ValidationError):
        Observation(confidence=1)


def test_frozen_and_extra_fields():
    observation = Observation(value=8000, confidence=1)
    with pytest.raises(ValidationError):
        observation.value = 5000
    with pytest.raises(ValidationError):
        Observation(value=8000, invented="data")


@pytest.mark.parametrize("width,height", [(1920,1080), (1280,720), (640,360)])
def test_normalized_scaling(width, height):
    image = np.zeros((height,width,3), np.uint8)
    image[height//4:height//2,width//4:width//2] = 255
    crop = Rect(x=.25,y=.25,width=.25,height=.25).crop(image)
    assert np.all(crop == 255)


@pytest.mark.parametrize("params", [{"x":.9,"y":0,"width":.2,"height":1}, {"x":0,"y":0,"width":0,"height":1}])
def test_invalid_geometry(params):
    with pytest.raises(ValidationError):
        Rect(**params)


def test_letterboxed_viewport():
    image = np.zeros((480,640,3), np.uint8)
    image[60:420] = 200
    calibration = Calibration(name="letterbox", viewport=Rect(x=0,y=.125,width=1,height=.75), regions={"a":Region(rect=Rect(x=0,y=0,width=1,height=1),kind="unobserved")})
    assert np.all(calibration.crop_regions(image)["a"] == 200)
    with pytest.raises(ValueError, match="aspect ratio"):
        Calibration(name="wrong",regions={}).crop_regions(image)
