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


class JapaneseHelpFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, prefix="使い方: " if prefix is None else prefix)


def desktop_rect(value: str):
    try:
        result = tuple(int(part) for part in value.split(","))
        if len(result) != 4 or result[0] < 0 or result[1] < 0 or result[2] <= result[0] or result[3] <= result[1]:
            raise ValueError
        return result
    except ValueError:
        raise argparse.ArgumentTypeError("正の幅・高さを持つ left,top,right,bottom を指定してください") from None


def normalized_rect(value: str):
    try:
        x,y,width,height = (float(part) for part in value.split(","))
        return Rect(x=x,y=y,width=width,height=height)
    except ValueError:
        raise argparse.ArgumentTypeError("0〜1に収まる正規化座標 x,y,width,height を指定してください") from None


def build_pipeline(calibration: Path, database: Path):
    db = CardDatabase(database)
    try:
        return Pipeline(Perception(load_calibration(calibration), calibration.parent, db, TesseractOCR(os.environ.get("TESSERACT_CMD", "tesseract"))))
    except Exception:
        db.close()
        raise


def run_advisor(args):
    if args.fps < 1 or args.fps > 240 or args.max_frames < 0:
        raise ValueError("FPS は1〜240、最大フレーム数は0以上で指定してください")
    if args.loop and not args.video:
        raise ValueError("繰り返しは録画再生でのみ利用できます")
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
            print(f"別画面のアドバイザーをローカルのポートで起動しました: {server.server_port}", flush=True)
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
                    # 履歴が最大件数に達しても現在のフレームの変化を保存します。
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
            print("録画再生が終了しました。古い推奨は取り消します。Ctrl+C で終了します。", flush=True)
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
    root = argparse.ArgumentParser(description="観測専用の Master Duel アドバイザーです。ゲームを操作しません")
    commands = root.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="合成データで一連の処理を検証します。実ゲームの検証ではありません")
    demo.add_argument("--output", type=Path, default=Path("artifacts/demo"))
    demo.add_argument("--results", type=Path, default=Path("evaluation/results.json"))
    evaluate_command = commands.add_parser("evaluate",help="正解ラベル付きデータで認識と推奨を評価します")
    evaluate_command.add_argument("--dataset", required=True, type=Path)
    evaluate_command.add_argument("--calibration", required=True, type=Path)
    evaluate_command.add_argument("--database", required=True, type=Path)
    evaluate_command.add_argument("--output", type=Path, default=Path("evaluation/results.json"))
    run = commands.add_parser("run",help="画面取得または録画再生から状態と推奨を生成します")
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
    run.add_argument("--loop",action="store_true",help="録画を繰り返し再生し、周回ごとに履歴を初期化します")
    run.add_argument("--ui", action="store_true")
    run.add_argument("--hold-ui", action="store_true")
    run.add_argument("--port", type=int, default=8765)
    bench = commands.add_parser("benchmark",help="取得・再生の処理速度と CPU 使用率を測ります")
    source = bench.add_mutually_exclusive_group(required=True)
    source.add_argument("--video", type=Path)
    source.add_argument("--rect", type=desktop_rect)
    bench.add_argument("--backend", choices=["dxcam", "mss"], default="dxcam")
    bench.add_argument("--fps", type=int, default=30)
    bench.add_argument("--seconds", type=float, default=30)
    bench.add_argument("--output", type=Path, default=Path("artifacts/benchmark.json"))
    validate = commands.add_parser("validate-calibration",help="校正の座標・ラベル・参照画像を確認します")
    validate.add_argument("path", type=Path)
    validate.add_argument("--database", type=Path, required=True)
    validate.add_argument("--image", type=Path)
    import_cards = commands.add_parser("import-cards",help="JSON のカード情報を SQLite に取り込みます")
    import_cards.add_argument("path", type=Path)
    import_cards.add_argument("--database", type=Path, required=True)
    snap = commands.add_parser("snapshot",help="指定したデスクトップ領域の画像を保存します")
    snap.add_argument("--rect", type=desktop_rect, required=True)
    snap.add_argument("--backend", choices=["dxcam", "mss"], default="mss")
    snap.add_argument("--output", type=Path, required=True)
    calibrate = commands.add_parser("calibrate-region",help="画面からユーザー指定の領域・ラベル付き参照画像を追加します")
    calibrate.add_argument("--calibration",type=Path,required=True)
    calibrate.add_argument("--image",type=Path,required=True)
    calibrate.add_argument("--region",required=True)
    calibrate.add_argument("--kind",choices=["number","template","card","action","unobserved"],required=True)
    calibrate.add_argument("--box",type=normalized_rect,required=True)
    calibrate.add_argument("--viewport",type=normalized_rect)
    calibrate.add_argument("--label")
    # 標準ヘルプの見出しと、このツールの各引数の説明を日本語にします。
    descriptions={"output":"結果の保存先", "results":"評価結果の保存先", "dataset":"正解ラベル付きデータの JSON", "calibration":"校正設定の JSON", "database":"カード情報の SQLite ファイル", "video":"再生する録画ファイル", "rect":"デスクトップ矩形 left,top,right,bottom", "backend":"画面の取得方式", "fps":"目標の毎秒フレーム数（1〜240）", "max_frames":"取得する最大枚数（0は制限なし）", "realtime":"録画を元の時間間隔で再生します", "ui":"別画面のアドバイザーを起動します", "hold_ui":"再生終了後も表示サービスを残します", "port":"ローカル表示サービスのポート", "seconds":"計測する秒数", "path":"読み込む設定またはカード情報のファイル", "image":"認識・校正に使う画像", "region":"観測領域の識別子", "kind":"領域の認識方式", "box":"正規化座標 x,y,width,height", "viewport":"表示範囲の正規化座標", "label":"参照画像の正解ラベル", "help":"この説明を表示して終了します"}
    for command_parser in [root,*commands.choices.values()]:
        command_parser.formatter_class=JapaneseHelpFormatter
        command_parser._positionals.title="コマンド・引数"
        command_parser._optionals.title="オプション"
        for argument in command_parser._actions:
            if argument.dest in descriptions:
                argument.help=descriptions[argument.dest]
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
                raise ValueError("正の計測時間と1〜240の FPS が必要です")
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
                        raise ValueError("検証用の画像を読み込めません")
                    pipeline.perception.calibration.crop_regions(pixels)
                print("校正の座標・ラベル・参照画像を確認しました。実ゲームの精度は未検証です")
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
            print(f"カード情報を{len(cards)}件取り込みました")
        elif args.command == "snapshot":
            source = LiveCaptureSource(args.backend, args.rect)
            try:
                frame = source.read()
                if frame is None:
                    raise ValueError("デスクトップの画像を取得できません")
                args.output.parent.mkdir(parents=True, exist_ok=True)
                if not cv2.imwrite(str(args.output), frame.pixels):
                    raise ValueError("画面を保存できません")
            finally:
                source.close()
        elif args.command == "calibrate-region":
            calibrate_region(args.calibration,args.image,args.region,args.kind,args.box,args.label,args.viewport)
            print("指定ラベルの校正領域を保存しました。ライブ利用前に校正確認と評価を行ってください")
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        print(f"設定・実行エラー: {exc}")
        return 2
