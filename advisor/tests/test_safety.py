import pytest

from master_duel_advisor.safety import ControlState, DesktopControl, GuardedClicker, InputBlocked


class Desktop:
    def __init__(self):
        self.keys = set()
        self.front = self.at = 123
        self.rect = (-1920, 816, -640, 1536)
        self.inputs = []
        self.after_move = None

    def key_down(self, key): return key in self.keys
    def foreground(self): return self.front
    def client_rect(self, hwnd): return self.rect
    def window_at(self, x, y): return self.at
    def move(self, x, y):
        self.inputs.append((x, y))
        if self.after_move:
            self.after_move()
    def click(self): self.inputs.append("click")


def setup():
    desktop = Desktop()
    control = DesktopControl(desktop, 123, (-1920, 785, -640, 1585))
    return desktop, control, GuardedClicker(control)


def test_f8_edges_toggle_and_f9_latches():
    d,c,_ = setup()
    d.keys = {c.F8}
    assert c.poll() == ControlState.PAUSED
    assert c.poll() == ControlState.PAUSED  # 押しっぱなしで反転しません。
    d.keys.clear()
    c.poll()
    d.keys.add(c.F8)
    assert c.poll() == ControlState.OBSERVING
    d.keys = {c.F9}
    assert c.stopped()
    d.keys = {c.F8}
    assert c.stopped()  # 緊急停止は再開できません。


@pytest.mark.parametrize("point", [(-1921,900),(-640,900),(-1800,800),(-1800,1536)])
def test_outside_capture_or_game_client_never_moves(point):
    d,c,clicker = setup()
    with pytest.raises(InputBlocked): clicker.click(*point)
    assert not d.inputs


def test_foreground_and_occlusion_required():
    d,c,clicker = setup()
    d.front = 999
    with pytest.raises(InputBlocked): clicker.click(-1800,900)
    assert not d.inputs
    d.front, d.at = 123,999
    with pytest.raises(InputBlocked): clicker.click(-1800,900)
    assert not d.inputs


def test_focus_change_during_cursor_move_never_clicks():
    d,c,clicker = setup()
    d.after_move = lambda: setattr(d, "front", 999)
    with pytest.raises(InputBlocked): clicker.click(-1800,900)
    assert d.inputs == [(-1800,900)]


def test_emergency_during_cursor_move_never_clicks():
    d,c,clicker = setup()
    d.after_move = lambda: d.keys.add(c.F9)
    with pytest.raises(InputBlocked): clicker.click(-1800,900)
    assert "click" not in d.inputs


def test_window_movement_requires_new_configuration():
    d,c,clicker = setup()
    d.rect = (-1910,816,-630,1536)
    with pytest.raises(InputBlocked): clicker.click(-1800,900)
    assert not d.inputs


def test_valid_click_and_escape_stop():
    d,c,clicker = setup()
    clicker.click(-1800,900)
    assert d.inputs == [(-1800,900),"click"]
    d.keys.add(c.ESC)
    with pytest.raises(InputBlocked): clicker.click(-1800,900)
