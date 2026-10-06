"""対象ウィンドウ・入力範囲・停止キーを入力層で検証します。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from enum import StrEnum


class ControlState(StrEnum):
    OBSERVING = "OBSERVING"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    ACTING = "ACTING"
    VERIFYING = "VERIFYING"
    STOPPED = "STOPPED"


class InputBlocked(RuntimeError):
    """入力前に拒否しました。入力結果不明のエラーとは区別します。"""


class WindowsDesktop:
    def __init__(self):
        if not hasattr(ctypes, "windll"):
            raise RuntimeError("実行にはWindowsが必要です")
        self.api = ctypes.windll.user32
        self.api.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        self.api.FindWindowW.restype = wintypes.HWND
        self.api.GetForegroundWindow.restype = wintypes.HWND
        self.api.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.api.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self.api.WindowFromPoint.argtypes = [wintypes.POINT]
        self.api.WindowFromPoint.restype = wintypes.HWND
        self.api.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.api.GetAncestor.restype = wintypes.HWND
        self.api.IsWindow.argtypes = [wintypes.HWND]
        self.api.IsWindowVisible.argtypes = [wintypes.HWND]
        self.api.IsIconic.argtypes = [wintypes.HWND]

    def find(self, title):
        hwnd = self.api.FindWindowW(None, title)
        if not hwnd:
            raise ValueError(f"対象ウィンドウが見つかりません: {title}")
        return hwnd

    def key_down(self, key):
        return bool(self.api.GetAsyncKeyState(key) & 0x8000)

    def foreground(self):
        return self.api.GetForegroundWindow()

    def client_rect(self, hwnd):
        if not self.api.IsWindow(hwnd) or not self.api.IsWindowVisible(hwnd) or self.api.IsIconic(hwnd):
            raise InputBlocked("対象ウィンドウが表示されていません")
        rect, origin = wintypes.RECT(), wintypes.POINT()
        if not self.api.GetClientRect(hwnd, ctypes.byref(rect)) or not self.api.ClientToScreen(hwnd, ctypes.byref(origin)):
            raise InputBlocked("現在のゲーム領域を確認できません")
        return origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom

    def window_at(self, x, y):
        hwnd = self.api.WindowFromPoint(wintypes.POINT(x, y))
        return self.api.GetAncestor(hwnd, 2) if hwnd else None

    def input_epoch(self):
        """同一Windows sessionの粗い最終入力token。時計減算や入力数の証明に使いません。"""
        class LastInput(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
        info = LastInput()
        info.cbSize = ctypes.sizeof(info)
        fn = self.api.GetLastInputInfo
        fn.argtypes = [ctypes.POINTER(LastInput)]
        fn.restype = wintypes.BOOL
        if not fn(ctypes.byref(info)):
            raise InputBlocked("入力活動の確認APIが失敗しました")
        return int(info.dwTime)

    def move(self, x, y):
        if not self.api.SetCursorPos(x, y):
            raise OSError("カーソルを移動できません")

    def click(self):
        self.api.mouse_event(0x0002, 0, 0, 0, 0)
        self.api.mouse_event(0x0004, 0, 0, 0, 0)


class DesktopControl:
    F8, F9, ESC = 0x77, 0x78, 0x1B

    def __init__(self, desktop, hwnd, screen_rect):
        self.desktop, self.hwnd, self.screen_rect = desktop, hwnd, screen_rect
        self.paused = False
        self.emergency = False
        self._f8_down = False
        self.state = ControlState.OBSERVING
        self.initial_client_rect = desktop.client_rect(hwnd)

    def poll(self):
        if self.desktop.key_down(self.F9) or self.desktop.key_down(self.ESC):
            self.emergency = True
        down = self.desktop.key_down(self.F8)
        if down and not self._f8_down and not self.emergency:
            self.paused = not self.paused
        self._f8_down = down
        if self.emergency:
            self.state = ControlState.STOPPED
        elif self.paused:
            self.state = ControlState.PAUSED
        elif self.desktop.foreground() != self.hwnd:
            self.state = ControlState.BLOCKED
        else:
            self.state = ControlState.OBSERVING
        return self.state

    def stopped(self):
        self.poll()
        return self.emergency

    def ready(self):
        return self.poll() == ControlState.OBSERVING

    def validate_point(self, x, y):
        if not self.ready():
            raise InputBlocked(f"入力を停止しています: {self.state}")
        client = self.desktop.client_rect(self.hwnd)
        if client != self.initial_client_rect:
            raise InputBlocked("ゲームウィンドウの位置またはサイズが変わりました。取得範囲を再設定してください")
        for l,t,r,b in [self.screen_rect, client]:
            if not l <= x < r or not t <= y < b:
                raise InputBlocked("クリック点が現在のゲーム領域または取得範囲の外です")
        if self.desktop.window_at(x, y) != self.hwnd:
            raise InputBlocked("クリック点を別のウィンドウが覆っています")


class GuardedClicker:
    def __init__(self, control: DesktopControl):
        self.control = control

    def input_epoch(self):
        if not self.control.ready():
            raise InputBlocked("入力活動の確認中に停止・前面切替がありました")
        client = self.control.desktop.client_rect(self.control.hwnd)
        if client != self.control.initial_client_rect:
            raise InputBlocked("入力活動の確認中にclient矩形が変化しました")
        return self.control.desktop.input_epoch()

    def click(self, x, y):
        self.control.validate_point(x, y)
        self.control.desktop.move(x, y)
        # カーソル移動中の前面切替・停止キーも検査します。
        self.control.validate_point(x, y)
        self.control.state = ControlState.ACTING
        self.control.desktop.click()
