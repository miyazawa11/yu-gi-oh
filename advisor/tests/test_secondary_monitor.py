import sys
from types import SimpleNamespace

import numpy as np
import pytest

from master_duel_advisor.capture import LiveCaptureSource
from master_duel_advisor.cli import desktop_rect


def test_mss_preserves_negative_desktop_coordinates(monkeypatch):
    calls = []
    camera = SimpleNamespace(
        grab=lambda region: (calls.append(region) or np.zeros((720, 1280, 4), np.uint8)),
        close=lambda: calls.append("close"),
    )
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "mss", SimpleNamespace(mss=lambda: camera))
    rect = desktop_rect("-1920,785,-640,1505")
    source = LiveCaptureSource("mss", rect)
    try:
        assert source.read().pixels.shape == (720, 1280, 3)
        assert calls == [{"left": -1920, "top": 785, "width": 1280, "height": 720}]
    finally:
        source.close()
    assert calls[-1] == "close"


def test_dxcam_negative_coordinates_require_mss(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(ValueError, match="MSS"):
        LiveCaptureSource("dxcam", (-1920, 785, -640, 1505))
