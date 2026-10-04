from __future__ import annotations

import time

import cv2
import numpy as np
import psutil

from .capture import CaptureSource


def benchmark(source: CaptureSource, seconds: float, target_fps: int, live: bool) -> dict:
    if seconds <= 0 or not 1 <= target_fps <= 240:
        raise ValueError("Duration must be positive and target FPS 1–240")
    process = psutil.Process()
    cpu_start = sum(process.cpu_times()[:2])
    started = time.monotonic()
    reads, received, unique = [], 0, 0
    last = None
    try:
        while time.monotonic()-started < seconds:
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
            # Lossy codecs change bytes between visually identical frames.
            # Count meaningful visual updates, not exact byte hashes.
            if last is None or float(np.mean(np.abs(thumbnail-last))) >= 0.005:
                unique += 1
                last = thumbnail
            if live:
                time.sleep(max(0, started+received/target_fps-time.monotonic()))
    finally:
        source.close()
    elapsed = time.monotonic()-started
    cpu_used = sum(process.cpu_times()[:2])-cpu_start
    expected = elapsed*target_fps
    return {"elapsed_seconds": elapsed, "frames_received": received, "unique_frames": unique, "received_fps": received/elapsed, "unique_fps": unique/elapsed, "visual_change_threshold": 0.005, "capture_read_ms_mean": float(np.mean(reads)) if reads else None, "capture_read_ms_p95": float(np.percentile(reads,95)) if reads else None, "cpu_percent_one_core": 100*cpu_used/elapsed, "gpu_percent": None, "estimated_scheduled_sample_miss_rate": max(0, 1-received/expected) if live else None, "actual_frame_drop_rate": None, "mode": "live" if live else "offline_replay", "limitations": ["Unique image rate estimates meaningful changes, not physical acquisition FPS", "Read duration is not acquisition latency", "Actual GPU utilization and frame drops require backend/instrumented measurement"]}
