from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import replace
from pathlib import Path

import cv2

from .advisor import SnapshotStore, start_server
from .benchmark import benchmark
from .calibration import calibrate_region
from .capture import LiveCaptureSource, VideoCaptureSource
from .cards import Card, CardDatabase
from .demo import generate_demo
from .evaluation import evaluate
from .perception import Perception, TesseractOCR
from .pipeline import FrameGate, Pipeline, save_json
from .regions import Rect, load_calibration
from .tracking import Tracker


def desktop_rect(value: str):
    try:
        result = tuple(int(part) for part in value.split(","))
        if len(result) != 4 or result[0] < 0 or result[1] < 0 or result[2] <= result[0] or result[3] <= result[1]:
            raise ValueError
        return result
    except ValueError:
        raise argparse.ArgumentTypeError("Use left,top,right,bottom with positive width/height") from None


def normalized_rect(value: str):
    try:
        x,y,width,height = (float(part) for part in value.split(","))
        return Rect(x=x,y=y,width=width,height=height)
    except ValueError:
        raise argparse.ArgumentTypeError("Use normalized x,y,width,height entirely within [0,1]") from None


def build_pipeline(calibration: Path, database: Path):
    db = CardDatabase(database)
    try:
        return Pipeline(Perception(load_calibration(calibration), calibration.parent, db, TesseractOCR(os.environ.get("TESSERACT_CMD", "tesseract"))))
    except Exception:
        db.close()
        raise


def run_advisor(args):
    if args.fps < 1 or args.fps > 240 or args.max_frames < 0:
        raise ValueError("FPS must be 1–240 and max-frames nonnegative")
    if args.loop and not args.video:
        raise ValueError("Loop is only available for replay")
    pipeline = build_pipeline(args.calibration, args.database)
    source = None
    server = None
    processed = 0
    store, gate = SnapshotStore(), FrameGate(calibration=pipeline.perception.calibration)
    started = time.monotonic()
    try:
        source = VideoCaptureSource(args.video, args.realtime) if args.video else LiveCaptureSource(args.backend, args.rect, args.fps)
        if args.ui:
            server, _ = start_server(store, args.port)
            print(f"Separate local Advisor UI listening on loopback port {server.server_port}", flush=True)
        args.output.mkdir(parents=True, exist_ok=True)
        with (args.output/"events.jsonl").open("w", encoding="utf-8") as events:
            captured = 0
            while not args.max_frames or captured < args.max_frames:
                before = time.perf_counter()
                frame = source.read()
                capture_ms = (time.perf_counter()-before)*1000
                if frame is None:
                    if args.video:
                        if args.loop and captured:
                            source.close()
                            source = VideoCaptureSource(args.video,args.realtime)
                            pipeline.tracker,gate = Tracker(),FrameGate(calibration=pipeline.perception.calibration)
                            continue
                        break
                    time.sleep(1/args.fps)
                    continue
                frame = replace(frame,sequence=captured)
                captured += 1
                if gate.accept(frame):
                    snapshot = pipeline.process(frame, capture_ms)
                    store.update(snapshot)
                    save_json(args.output/"latest.json", snapshot)
                    # Persist current frame's changes even when the history deque wraps.
                    for event in pipeline.tracker.events:
                        if event.timestamp == frame.captured_at:
                            events.write(event.model_dump_json()+"\n")
                    events.flush()
                    processed += 1
                if not args.video:
                    time.sleep(max(0, 1/args.fps-(time.perf_counter()-before)))
        summary = {"captured": captured, "processed": processed, "elapsed_seconds": time.monotonic()-started, "api_calls": 0, "api_cost_usd": 0, "mode": "replay" if args.video else "live"}
        save_json(args.output/"run.json", summary)
        print(json.dumps(summary), flush=True)
        if args.ui and args.hold_ui:
            print("Replay finished; UI marks advice stale. Press Ctrl+C to close.", flush=True)
            while True:
                time.sleep(0.25)
    finally:
        if source:
            source.close()
        if server:
            server.shutdown()
            server.server_close()
        pipeline.perception.cards.close()


def parser():
    root = argparse.ArgumentParser(description="Observation-only Master Duel advisor; never controls the game")
    commands = root.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Synthetic end-to-end fixture; not real-game validation")
    demo.add_argument("--output", type=Path, default=Path("artifacts/demo"))
    demo.add_argument("--results", type=Path, default=Path("evaluation/results.json"))
    evaluate_command = commands.add_parser("evaluate")
    evaluate_command.add_argument("--dataset", required=True, type=Path)
    evaluate_command.add_argument("--calibration", required=True, type=Path)
    evaluate_command.add_argument("--database", required=True, type=Path)
    evaluate_command.add_argument("--output", type=Path, default=Path("evaluation/results.json"))
    run = commands.add_parser("run")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--video", type=Path)
    source.add_argument("--rect", type=desktop_rect)
    run.add_argument("--backend", choices=["dxcam", "mss"], default="dxcam")
    run.add_argument("--fps", type=int, default=30)
    run.add_argument("--calibration", type=Path, required=True)
    run.add_argument("--database", type=Path, required=True)
    run.add_argument("--output", type=Path, default=Path("artifacts/run"))
    run.add_argument("--max-frames", type=int, default=0)
    run.add_argument("--realtime", action="store_true")
    run.add_argument("--loop",action="store_true",help="Loop replay, resetting temporal history at each boundary")
    run.add_argument("--ui", action="store_true")
    run.add_argument("--hold-ui", action="store_true")
    run.add_argument("--port", type=int, default=8765)
    bench = commands.add_parser("benchmark")
    source = bench.add_mutually_exclusive_group(required=True)
    source.add_argument("--video", type=Path)
    source.add_argument("--rect", type=desktop_rect)
    bench.add_argument("--backend", choices=["dxcam", "mss"], default="dxcam")
    bench.add_argument("--fps", type=int, default=30)
    bench.add_argument("--seconds", type=float, default=30)
    bench.add_argument("--output", type=Path, default=Path("artifacts/benchmark.json"))
    validate = commands.add_parser("validate-calibration")
    validate.add_argument("path", type=Path)
    validate.add_argument("--database", type=Path, required=True)
    validate.add_argument("--image", type=Path)
    import_cards = commands.add_parser("import-cards")
    import_cards.add_argument("path", type=Path)
    import_cards.add_argument("--database", type=Path, required=True)
    snap = commands.add_parser("snapshot")
    snap.add_argument("--rect", type=desktop_rect, required=True)
    snap.add_argument("--backend", choices=["dxcam", "mss"], default="mss")
    snap.add_argument("--output", type=Path, required=True)
    calibrate = commands.add_parser("calibrate-region",help="Append a user-labeled region/exemplar from a screenshot")
    calibrate.add_argument("--calibration",type=Path,required=True)
    calibrate.add_argument("--image",type=Path,required=True)
    calibrate.add_argument("--region",required=True)
    calibrate.add_argument("--kind",choices=["number","template","card","action","unobserved"],required=True)
    calibrate.add_argument("--box",type=normalized_rect,required=True)
    calibrate.add_argument("--viewport",type=normalized_rect)
    calibrate.add_argument("--label")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "run":
            run_advisor(args)
        elif args.command == "demo":
            assets = generate_demo(args.output)
            pipeline = build_pipeline(assets["calibration"], assets["database"])
            try:
                report = evaluate(assets["dataset"], pipeline, args.results)
            finally:
                pipeline.perception.cards.close()
            print(json.dumps({"dataset_kind": report["dataset_kind"], "samples": report["sample_count"], "state_accuracy": report["game_state_exact_accuracy"], "action_accuracy": report["action_exact_accuracy"], "real_perception_gate_passed": report["real_perception_gate_passed"]}))
            return 0 if not report["errors"] else 1
        elif args.command == "evaluate":
            pipeline = build_pipeline(args.calibration, args.database)
            try:
                report = evaluate(args.dataset, pipeline, args.output)
            finally:
                pipeline.perception.cards.close()
            print(json.dumps({"errors": len(report["errors"]), "real_perception_gate_passed": report["real_perception_gate_passed"]}))
            return 0 if not report["errors"] else 1
        elif args.command == "benchmark":
            if args.seconds <= 0 or not 1 <= args.fps <= 240:
                raise ValueError("Positive duration and FPS 1–240 required")
            source = VideoCaptureSource(args.video) if args.video else LiveCaptureSource(args.backend, args.rect, args.fps)
            report = benchmark(source, args.seconds, args.fps, not bool(args.video))
            save_json(args.output, report)
            print(json.dumps(report))
        elif args.command == "validate-calibration":
            pipeline = build_pipeline(args.path, args.database)
            try:
                if args.image:
                    pixels = cv2.imread(str(args.image))
                    if pixels is None:
                        raise ValueError("Cannot read validation image")
                    pipeline.perception.calibration.crop_regions(pixels)
                print("Calibration geometry, semantics and template assets validated; real accuracy unverified")
            finally:
                pipeline.perception.cards.close()
        elif args.command == "import-cards":
            cards = [Card.model_validate(card) for card in json.loads(args.path.read_text(encoding="utf-8"))]
            args.database.parent.mkdir(parents=True, exist_ok=True)
            db = CardDatabase(args.database)
            try:
                db.import_cards(cards)
            finally:
                db.close()
            print(f"Imported {len(cards)} card records")
        elif args.command == "snapshot":
            source = LiveCaptureSource(args.backend, args.rect)
            try:
                frame = source.read()
                if frame is None:
                    raise ValueError("No desktop frame available")
                args.output.parent.mkdir(parents=True, exist_ok=True)
                if not cv2.imwrite(str(args.output), frame.pixels):
                    raise ValueError("Cannot save snapshot")
            finally:
                source.close()
        elif args.command == "calibrate-region":
            calibrate_region(args.calibration,args.image,args.region,args.kind,args.box,args.label,args.viewport)
            print("Saved explicitly labeled calibration region; validate and evaluate before live use")
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        print(f"Setup/runtime error: {exc}")
        return 2
