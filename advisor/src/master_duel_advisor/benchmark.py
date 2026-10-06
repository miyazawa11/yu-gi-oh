from __future__ import annotations

import time

import cv2
import numpy as np
import psutil

from .capture import CaptureSource


def benchmark(source: CaptureSource, seconds: float, target_fps: int, live: bool) -> dict:
    if seconds <= 0 or not 1 <= target_fps <= 240:
        raise ValueError("計測時間は正の値、目標 FPS は1〜240で指定してください")
    process = psutil.Process()
    cpu_start = sum(process.cpu_times()[:2])
    started = time.perf_counter()
    reads, received, unique = [], 0, 0
    last = None
    try:
        while time.perf_counter()-started < seconds:
            before = time.perf_counter()
            frame = source.read()
            reads.append((time.perf_counter()-before)*1000)
            if frame is None:
                if live:
                    time.sleep(1/target_fps)
                    continue
                break
            received += 1
            thumbnail = cv2.resize(frame.pixels, (160, 90)).astype(np.float32)/255
            # 非可逆圧縮は見た目が同じフレームの画素値も変化させます。
            # 画素値の完全一致ではなく意味のある画像更新を数えます。
            if last is None or float(np.mean(np.abs(thumbnail-last))) >= 0.005:
                unique += 1
                last = thumbnail
            if live:
                time.sleep(max(0, started+received/target_fps-time.perf_counter()))
    finally:
        source.close()
    elapsed = max(time.perf_counter()-started, 1e-9)
    cpu_used = sum(process.cpu_times()[:2])-cpu_start
    expected = elapsed*target_fps
    return {"elapsed_seconds": elapsed, "frames_received": received, "unique_frames": unique, "received_fps": received/elapsed, "unique_fps": unique/elapsed, "visual_change_threshold": 0.005, "capture_read_ms_mean": float(np.mean(reads)) if reads else None, "capture_read_ms_p95": float(np.percentile(reads,95)) if reads else None, "cpu_percent_one_core": 100*cpu_used/elapsed, "gpu_percent": None, "estimated_scheduled_sample_miss_rate": max(0, 1-received/expected) if live else None, "actual_frame_drop_rate": None, "mode": "live" if live else "offline_replay", "limitations": ["更新率は意味のある画像変化の推定値であり、実際の画面取得 FPS ではありません", "読み取り時間は画面変化から取得までの遅延ではありません", "実際の GPU 使用率とフレーム落ちは別の実機計測が必要です"]}
