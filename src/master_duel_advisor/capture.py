from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np


@dataclass(frozen=True)
class Frame:
    pixels: np.ndarray  # 全取得方式で BGR uint8 に統一します。
    captured_at: float  # 単調増加時計による受領時刻です。物理的な取得遅延ではありません。
    sequence: int
    media_time: float | None = None


class CaptureSource(Protocol):
    def read(self) -> Frame | None: ...
    def close(self) -> None: ...


class VideoCaptureSource:
    def __init__(self, path: Path, realtime: bool = False):
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise ValueError(f"録画を開けません: {path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        if not np.isfinite(self.fps) or self.fps <= 0:
            self.cap.release()
            raise ValueError("録画には有効な FPS が必要です")
        self.realtime, self.sequence = realtime, 0
        self.started = time.monotonic()

    def read(self) -> Frame | None:
        ok, pixels = self.cap.read()
        if not ok:
            return None
        media_time = self.sequence / self.fps
        if self.realtime:
            time.sleep(max(0, self.started + media_time - time.monotonic()))
        frame = Frame(pixels, time.monotonic(), self.sequence, media_time)
        self.sequence += 1
        return frame

    def close(self):
        self.cap.release()


class ImageCaptureSource:
    def __init__(self, paths: list[Path]):
        self.paths = iter(paths)
        self.sequence = 0

    def read(self) -> Frame | None:
        path = next(self.paths, None)
        if path is None:
            return None
        pixels = cv2.imread(str(path))
        if pixels is None:
            raise ValueError(f"画像を読み込めません: {path}")
        frame = Frame(pixels, time.monotonic(), self.sequence)
        self.sequence += 1
        return frame

    def close(self):
        pass


class LiveCaptureSource:
    """ユーザー指定のデスクトップ矩形を取得します。ゲームは操作しません。"""

    def __init__(self, backend: str, rect: tuple[int, int, int, int], fps: int = 30):
        if sys.platform != "win32":
            raise RuntimeError("ライブ取得には Windows 11 が必要です。この環境では録画再生を使ってください")
        left, top, right, bottom = rect
        if left < 0 or top < 0 or right <= left or bottom <= top:
            raise ValueError("矩形は正の幅・高さを持つデスクトップ座標 left,top,right,bottom で指定してください")
        if not 1 <= fps <= 240:
            raise ValueError("FPS は1〜240で指定してください")
        self.backend, self.rect, self.sequence = backend, rect, 0
        self.camera = None
        if backend == "dxcam":
            import dxcam
            self.camera = dxcam.create(output_color="BGR")
        elif backend == "mss":
            import mss
            self.camera = mss.mss()
        else:
            raise ValueError(f"未対応の取得方式です: {backend}")

    def read(self) -> Frame | None:
        if self.backend == "dxcam":
            # 静止・取得不能な画面で待ち続ける get_latest_frame() の代わりに定期取得します。
            # 呼び出し間隔は取得元を利用する側で制御します。
            pixels = self.camera.grab(region=self.rect)
            if pixels is None:
                return None
            pixels = pixels.copy()
        else:
            l, t, r, b = self.rect
            pixels = np.asarray(self.camera.grab({"left": l, "top": t, "width": r-l, "height": b-t}))[:, :, :3].copy()
        frame = Frame(pixels, time.monotonic(), self.sequence)
        self.sequence += 1
        return frame

    def close(self):
        if self.camera is not None:
            if self.backend == "dxcam":
                self.camera.release()
            else:
                self.camera.close()
