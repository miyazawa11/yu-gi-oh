from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import replace
from pathlib import Path

import cv2

from .image_io import read_image, write_image

from .advisor import SnapshotStore, start_server
from .agent_loop import LoopLimits, make_live_loop
from .benchmark import benchmark
from .calibration import calibrate_region
from .capture import LiveCaptureSource, VideoCaptureSource
from .cards import Card, CardDatabase
from .card_knowledge import CardKnowledge, BackgroundKnowledge, DEFAULT_CACHE
from .demo import generate_demo
from .evaluation import evaluate
from .perception import Perception, TesseractOCR
from .pipeline import FrameGate, Pipeline, save_json
from .regions import Rect, load_calibration
from .tracking import Tracker
from .planning import PlanBook, TurnPlanner
from .strategy_rules import load_planner
from .ui_policy import UiPolicy
from .deck import DeckProfile
from .card_graph import CardGraph, Edge
from .dataset import export_dataset
from .chatgpt_auth import ChatGPTAuth, ConnectionStore, DEFAULT_STORAGE
from .chatgpt_strategy import ChatGPTStrategy
from .llm_fallback import StrategyFallback
from .local_strategy import LocalStrategy
from .chatgpt_transport import ChatGPTError, Transport


def enable_chatgpt(pipeline, args):
    if not math.isfinite(args.llm_timeout) or not 0 < args.llm_timeout <= 10:
        raise ValueError("判断の上限は10秒です。--llm-timeoutは0より大きく10以下にしてください")
    if args.local_model:
        if args.chatgpt:
            raise ValueError("--local-modelと--chatgptは同時に指定できません")
        pipeline.strategy_fallback = StrategyFallback(
            LocalStrategy(args.local_model, args.local_url, args.llm_timeout),
            max_calls=args.llm_max_calls, timeout=args.llm_timeout, cooldown=args.llm_cooldown)
        return
    if not args.chatgpt:
        return
    if not args.chatgpt_model:
        raise ValueError("chatgpt-modelsで確認したslugを--chatgpt-modelに指定してください")
    auth = ChatGPTAuth(ConnectionStore(args.chatgpt_storage),Transport(args.llm_timeout))
    status = auth.status()
    active = next((p for p in status["profiles"] if p["id"]==status["active"]),None)
    if not active or not active["signed_in"] or not active["plan_enabled"]:
        raise ChatGPTError("login_or_plan_permission_required")
    pipeline.strategy_fallback = StrategyFallback(ChatGPTStrategy(auth,args.chatgpt_model),
        max_calls=args.llm_max_calls, timeout=args.llm_timeout, cooldown=args.llm_cooldown)


def close_pipeline(pipeline):
    if pipeline.strategy_fallback:
        pipeline.strategy_fallback.close()
    pipeline.perception.cards.close()


class JapaneseHelpFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, prefix="使い方: " if prefix is None else prefix)


def desktop_rect(value: str):
    try:
        result = tuple(int(part) for part in value.split(","))
        if len(result) != 4 or result[2] <= result[0] or result[3] <= result[1]:
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


def build_pipeline(calibration: Path, database: Path, plan_book: Path | None = None,
                   ui_rules: Path | None = None, deck: Path | None = None,
                   card_cache: Path | None = None, card_id_namespace: str = "konami"):
    required = {"--calibration": calibration, "--database": database,
                "--plan-book": plan_book, "--ui-rules": ui_rules, "--deck": deck}
    missing = [f"{option}: {Path(path).resolve()}" for option, path in required.items()
               if path is not None and not Path(path).is_file()]
    if missing:
        raise ValueError("必要な設定ファイルがありません。\n" + "\n".join(missing)
                         + "\ndata/*.json と data/cards.sqlite3 は設定例です。実画面用の校正・カードDB・デッキ・操作手順を用意してください。")
    knowledge = BackgroundKnowledge(CardKnowledge(card_cache), card_id_namespace) if card_cache else None
    db = CardDatabase(database, knowledge=knowledge)
    try:
        profile = DeckProfile.load(deck) if deck else None
        layout = load_calibration(calibration)
        planner = load_planner(plan_book) if plan_book else None
        if planner and (any(r.follows for r in getattr(planner.book, "rules", []))
                        or planner.book.audit_profile in {"response_decline", "solo_basic_operations"}):
            from .route_validation import audit_route
            report = audit_route(planner.book, layout, calibration.parent)
            if not report["structural_ready"]:
                names = ", ".join(item["region"] for item in report["missing"])
                raise ValueError("段階付き手順の画面校正が不足しています: " + names)
        perception = Perception(layout, calibration.parent, db, TesseractOCR(os.environ.get("TESSERACT_CMD", "tesseract")),
                                allowed_card_ids=profile.recognition_ids if profile else None)
        policy = UiPolicy.load(ui_rules) if ui_rules else UiPolicy()
        inspection = next((r.logical_inspect_confirmation for r in getattr(getattr(planner, "book", None), "rules", [])
                           if r.logical_inspect_confirmation is not None), None)
        if inspection is not None:
            perception.configure_inspect(inspection, calibration.parent,
                                        config_files=[calibration, plan_book])
        responses = {r.logical_response_decline.kind: r.logical_response_decline
                     for r in getattr(getattr(planner, "book", None), "rules", []) if r.logical_response_decline}
        if responses:
            policy.validate_responses(planner.book)
            perception.configure_responses(list(responses.values()), calibration.parent,
                                           config_files=[calibration, plan_book, ui_rules])
        hand_goals=[r.logical_hand_search_confirmation for r in getattr(getattr(planner,"book",None),"rules",[])
                    if r.logical_hand_search_confirmation is not None]
        if hand_goals:
            if any(g!=hand_goals[0] for g in hand_goals):raise ValueError("hand-search複数goalは未対応です")
            policy.validate_hands(planner.book)
            perception.hand_logical_action=next(r.logical_action for r in planner.book.rules if r.logical_hand_search_confirmation)
            perception.configure_hand_search(hand_goals[0],calibration.parent)
        return Pipeline(perception,
                        planner=planner,
                        ui_policy=policy)
    except Exception:
        db.close()
        raise


def run_advisor(args):
    if args.fps < 1 or args.fps > 240 or args.max_frames < 0:
        raise ValueError("FPS は1〜240、最大フレーム数は0以上で指定してください")
    if args.loop and not args.video:
        raise ValueError("繰り返しは録画再生でのみ利用できます")
    pipeline = build_pipeline(args.calibration, args.database, args.plan_book, args.ui_rules, args.deck,
                              None if args.offline_cards else args.card_cache, args.card_id_namespace)
    source = None
    server = None
    processed = 0
    store, gate = SnapshotStore(), FrameGate(calibration=pipeline.perception.calibration)
    started = time.monotonic()
    try:
        enable_chatgpt(pipeline,args)
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
                            if pipeline.planner:
                                pipeline.planner.reset()
                            continue
                        break
                    time.sleep(1/args.fps)
                    continue
                frame = replace(frame,sequence=captured)
                captured += 1
                strategy = pipeline.strategy_fallback
                ready = strategy is not None and strategy.future is not None and strategy.future.done()
                if gate.accept(frame) or ready or pipeline.decision_due:
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
        summary = {"captured": captured, "processed": processed, "elapsed_seconds": time.monotonic()-started,
                   "api_calls": pipeline.strategy_fallback.calls if pipeline.strategy_fallback else 0,
                   "api_cost_usd": None if pipeline.strategy_fallback else 0,
                   "mode": "replay" if args.video else "live"}
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
        close_pipeline(pipeline)


def parser():
    root = argparse.ArgumentParser(description="Master Duel の画面観測・限定ルールの助言と、明示起動の操作ループ")
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
    run.add_argument("--plan-book", type=Path, help="公開情報に基づく展開手順の JSON")
    run.add_argument("--ui-rules", type=Path, help="確認UIの意味と対応行動を登録したJSON")
    run.add_argument("--deck", type=Path, help="認識対象の1デッキと汎用カードのJSON")
    run.add_argument("--output", type=Path, default=Path("artifacts/run"))
    run.add_argument("--max-frames", type=int, default=0)
    run.add_argument("--realtime", action="store_true")
    run.add_argument("--loop",action="store_true",help="録画を繰り返し再生し、周回ごとに履歴を初期化します")
    run.add_argument("--ui", action="store_true")
    run.add_argument("--hold-ui", action="store_true")
    run.add_argument("--port", type=int, default=8765)
    agent = commands.add_parser("agent-loop", help="校正済み UI ボタンを認識・操作する反復型ループ")
    agent.add_argument("--rect", type=desktop_rect, required=True)
    agent.add_argument("--calibration", type=Path, required=True)
    agent.add_argument("--database", type=Path, required=True)
    agent.add_argument("--plan-book", type=Path, help="公開情報に基づく展開手順の JSON")
    agent.add_argument("--ui-rules", type=Path, help="確認UIの意味と対応行動を登録したJSON")
    agent.add_argument("--deck", type=Path, help="認識対象の1デッキと汎用カードのJSON")
    agent.add_argument("--ui", action="store_true", help="状態・次行動・プラン・遅延をローカル表示します")
    agent.add_argument("--port", type=int, default=8765)
    agent.add_argument("--fast", action=argparse.BooleanOptionalAction, default=True,
                       help="既定で待機0秒・確認周期0.05秒。--no-fastで従来の待機に戻します")
    agent.add_argument("--window-title", default="masterduel", help="前面と入力先を検査する対象ウィンドウの完全タイトル")
    agent.add_argument("--settle-seconds", type=float, help="操作前の待機秒数（fast 時0、通常0.5）")
    agent.add_argument("--verify-poll-seconds", type=float, help="操作結果の確認周期（fast 時0.05、通常0.2）")
    agent.add_argument("--verify-seconds", type=float, default=3, help="各操作の結果確認上限秒。KPI達成時間とは別です")
    agent.add_argument("--output", type=Path, default=Path("artifacts/agent"))
    agent.add_argument("--fps", type=int, default=20)
    agent.add_argument("--max-seconds", type=float, default=300)
    agent.add_argument("--benchmark-trials", type=Path, help="画像取得前に登録する目的IDのJSON配列。認識失敗も試行分母に含めます")
    agent.add_argument("--run-purpose", choices=["pilot", "baseline", "acceptance"], default="pilot")
    agent.add_argument("--cohort-manifest", type=Path, help="本試験前に固定した版・設定・全試行slotのJSON")
    agent.add_argument("--cohort-slot", help="manifestに登録済みの今回のslot ID")
    agent.add_argument("--execution-context", type=Path, help="デッキ・ソロモード等の試験条件JSON（本試験必須）")
    agent.add_argument("--max-actions", type=int, default=100, help="子UI操作の上限。KPIの目的達成件数とは別です")
    agent.add_argument("--min-confidence", type=float, default=0.98)
    agent.add_argument("--max-retries", type=int, default=1)
    agent.add_argument("--max-same-action", type=int, default=3)
    for p in [run,agent]:
        p.add_argument("--card-cache", type=Path, default=DEFAULT_CACHE, help="未保存カードの自動取得先SQLite")
        p.add_argument("--card-id-namespace", choices=["konami", "ygoprodeck"], default="konami",
                       help="接頭辞のない校正カードIDの種類（既存設定はkonami）")
        p.add_argument("--offline-cards", action="store_true", help="カードAPIの自動取得を無効にします")
        p.add_argument("--local-model", help="Ollamaに取得済みのローカルモデル名")
        p.add_argument("--local-url", default="http://127.0.0.1:11434", help="OllamaのループバックURL")
        p.add_argument("--chatgpt",action="store_true",help="保存したChatGPT接続で例外戦略を判断します。APIキーは使いません")
        p.add_argument("--chatgpt-model",help="chatgpt-modelsに表示された利用可能モデルのslug")
        p.add_argument("--chatgpt-storage",type=Path,default=DEFAULT_STORAGE,help="保護されたChatGPT接続の保存フォルダー")
        p.add_argument("--llm-max-calls",type=int,default=5,help="1実行の例外判断呼出し上限")
        p.add_argument("--llm-timeout",type=float,default=10,help="例外判断の応答期限（最大10秒）。期限では最新候補の信頼度順で強制選択")
        p.add_argument("--llm-cooldown",type=float,default=30,help="例外判断を再要求する最短間隔秒")
    for name,help_text in [("chatgpt-login","ブラウザでSign in with ChatGPTを行います"),
                           ("chatgpt-status","接続状態を表示します。認証情報は出力しません"),
                           ("chatgpt-models","選択したアカウントの利用可能モデルを表示します"),
                           ("chatgpt-select","保存済みのChatGPT接続を選びます"),
                           ("chatgpt-logout","選択した接続の更新トークンを失効させてサインアウトします")]:
        p=commands.add_parser(name,help=help_text)
        p.add_argument("--storage",type=Path,default=DEFAULT_STORAGE,help="保護された接続の保存フォルダー")
        if name=="chatgpt-login":
            p.add_argument("--new",action="store_true",help="別アカウント／ワークスペースを新規登録します")
            p.add_argument("--profile",help="再認証する保存済み登録のID")
            p.add_argument("--no-browser",action="store_true",help="ブラウザを起動せずローカル開始URLを表示します")
            p.add_argument("--timeout",type=float,default=300,help="本人によるログイン完了の待機秒数")
        if name=="chatgpt-select": p.add_argument("profile",help="選択する保存済み登録のID")
    e2e = commands.add_parser("e2e-benchmark", help="目的単位の実機ログを集計します（ゲーム入力なし）")
    e2e.add_argument("logs", type=Path, nargs="+")
    e2e.add_argument("--reviews", type=Path, nargs="*", help="子入力の独立誤クリックレビューJSONL")
    e2e.add_argument("--cohort-manifest", type=Path, help="事前固定manifest。未指定では参考統計のみ")
    e2e.add_argument("--output", type=Path, default=Path("evaluation/e2e-benchmark.json"))
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
    cache_card = commands.add_parser("cache-card", help="カード原文をローカル優先で取得・保存します")
    lookup = cache_card.add_mutually_exclusive_group(required=True)
    lookup.add_argument("--konami-id")
    lookup.add_argument("--passcode")
    lookup.add_argument("--name", help="英語の正式名。日本語名はIDの照合が必要です")
    cache_card.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    cache_card.add_argument("--refresh", action="store_true", help="保存済みの原文を明示的に再取得します")
    graph_import = commands.add_parser("import-graph", help="出典・条件付きカード関係をSQLiteへ登録します")
    graph_import.add_argument("path", type=Path)
    graph_import.add_argument("--database", type=Path, required=True)
    graph_paths = commands.add_parser("graph-paths", help="カード関係を深さ制限付きで探索します。行動の合法性は判断しません")
    graph_paths.add_argument("--database", type=Path, required=True)
    graph_paths.add_argument("--source", required=True)
    graph_paths.add_argument("--target", required=True)
    graph_paths.add_argument("--depth", type=int, default=4)
    dataset = commands.add_parser("export-dataset", help="確認済み操作ログをstate→actionのJSONLへ変換します")
    dataset.add_argument("path", type=Path)
    dataset.add_argument("--output", type=Path, required=True)
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
    descriptions={"output":"結果の保存先", "results":"評価結果の保存先", "dataset":"正解ラベル付きデータの JSON", "calibration":"校正設定の JSON", "database":"カード情報の SQLite ファイル", "video":"再生する録画ファイル", "rect":"デスクトップ矩形 left,top,right,bottom", "backend":"画面の取得方式", "fps":"目標の毎秒フレーム数（1〜240）", "max_frames":"取得する最大枚数（0は制限なし）", "realtime":"録画を元の時間間隔で再生します", "ui":"別画面のアドバイザーを起動します", "hold_ui":"再生終了後も表示サービスを残します", "port":"ローカル表示サービスのポート", "seconds":"計測する秒数", "path":"読み込む設定またはカード情報のファイル", "image":"認識・校正に使う画像", "region":"領域の識別子", "kind":"領域の認識方式", "box":"正規化座標 x,y,width,height", "viewport":"表示範囲の正規化座標", "label":"参照画像の正解ラベル", "help":"この説明を表示して終了します", "max_seconds":"連続実行時間の上限", "max_actions":"クリック数の上限", "min_confidence":"操作に必要な最低認識信頼度", "max_retries":"失敗後に認める再試行数", "max_same_action":"同じボタンの連続上限"}
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
        if args.command.startswith("chatgpt-"):
            auth=ChatGPTAuth(ConnectionStore(args.storage))
            if args.command=="chatgpt-login":
                result=auth.login(args.profile,args.new,args.timeout,not args.no_browser,announce=lambda s:print(s,flush=True))
            elif args.command=="chatgpt-status": result=auth.status()
            elif args.command=="chatgpt-models": result=ChatGPTStrategy(auth).catalog()
            elif args.command=="chatgpt-select": auth.select(args.profile);result=auth.status()
            else: result=auth.logout()
            print(json.dumps(result,ensure_ascii=False),flush=True)
        elif args.command == "run":
            run_advisor(args)
        elif args.command == "agent-loop":
            if args.run_purpose == "acceptance" and not args.offline_cards:
                raise ValueError("本試験は事前充填済みDBと--offline-cardsが必須です")
            if not 1 <= args.fps <= 60:
                raise ValueError("FPS は1〜60で指定してください")
            pipeline = build_pipeline(args.calibration, args.database, args.plan_book, args.ui_rules, args.deck,
                                      None if args.offline_cards else args.card_cache, args.card_id_namespace)
            server = None
            args.output.mkdir(parents=True, exist_ok=True)
            performance_log = (args.output / "performance.jsonl").open("a",encoding="utf-8",buffering=1)
            store = None
            try:
                enable_chatgpt(pipeline,args)
                if args.ui:
                    store = SnapshotStore()
                    server, _ = start_server(store, args.port)
                    print(f"状態と計測の表示: http://127.0.0.1:{server.server_port}", flush=True)
                def publish(snapshot):
                    performance_log.write(json.dumps({"sequence":snapshot["state"]["sequence"],
                        "captured_at":snapshot["state"]["captured_at"],"metrics":snapshot["metrics"],
                        "planner_source":snapshot["planner_source"]},ensure_ascii=False,allow_nan=False)+"\n")
                    if store:
                        store.update(snapshot)
                pipeline.snapshot_sink = publish
                limits = LoopLimits(max_seconds=args.max_seconds, max_actions=args.max_actions,
                                    min_confidence=args.min_confidence, max_retries=args.max_retries,
                                    max_same_action=args.max_same_action,
                                    verify_seconds=args.verify_seconds,
                                    settle_seconds=args.settle_seconds if args.settle_seconds is not None else (0 if args.fast else .5),
                                    verify_poll_seconds=args.verify_poll_seconds if args.verify_poll_seconds is not None else (.05 if args.fast else .2))
                from .telemetry import load_trials
                trials = load_trials(args.benchmark_trials, pipeline.planner) if args.benchmark_trials else None
                if args.run_purpose == "acceptance" and (not trials or not args.execution_context):
                    raise ValueError("本試験には予定trialとexecution-contextが必要です")
                import hashlib
                execution = {key: getattr(args, key) for key in ("offline_cards", "card_id_namespace", "local_model", "local_url",
                             "chatgpt", "chatgpt_model", "llm_max_calls", "llm_timeout", "llm_cooldown", "ui")}
                execution["data_sha256"] = {key: hashlib.sha256(Path(getattr(args, key)).read_bytes()).hexdigest()
                                            for key in ("database", "deck", "plan_book", "ui_rules") if getattr(args, key, None)}
                execution["data_files"] = {key: {"path": str(Path(getattr(args, key)).resolve()), "sha256": digest}
                                           for key, digest in execution["data_sha256"].items()}
                execution["context"] = json.loads(args.execution_context.read_text(encoding="utf-8")) if args.execution_context else None
                summary = make_live_loop(pipeline, args.rect, args.output, args.fps, limits, args.window_title, trials,
                                         args.run_purpose, args.cohort_manifest, args.cohort_slot, execution).run()
                print(json.dumps(summary, ensure_ascii=False), flush=True)
            finally:
                performance_log.close()
                close_pipeline(pipeline)
                if server:
                    server.shutdown()
                    server.server_close()
        elif args.command == "cache-card":
            kind, value = (("konami_id", args.konami_id) if args.konami_id else
                           ("id", args.passcode) if args.passcode else ("name", args.name))
            record = CardKnowledge(args.cache).ensure(kind, value, refresh=args.refresh)
            print(json.dumps({"cache": str(args.cache.resolve()), "card_id": record["card"]["card_id"],
                              "name": record["card"]["name"], "language": record["language"],
                              "fetched_at": record["fetched_at"], "source_url": record["source_url"],
                              "master_duel_verified": record["master_duel_verified"]}, ensure_ascii=False))
        elif args.command == "export-dataset":
            print(json.dumps(export_dataset(args.path, args.output), ensure_ascii=False))
        elif args.command in {"import-graph", "graph-paths"}:
            args.database.parent.mkdir(parents=True, exist_ok=True)
            graph = CardGraph(args.database)
            try:
                if args.command == "import-graph":
                    edges = [Edge.model_validate(e) for e in json.loads(args.path.read_text(encoding="utf-8"))]
                    graph.import_edges(edges)
                    print(f"カード関係を{len(edges)}件登録しました")
                else:
                    print(json.dumps([[e.model_dump(mode="json") for e in path]
                                      for path in graph.paths(args.source,args.target,args.depth)], ensure_ascii=False))
            finally:
                graph.close()
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
        elif args.command == "e2e-benchmark":
            from .telemetry import summarize
            report = summarize(args.logs, reviews=args.reviews, cohort_manifest=args.cohort_manifest)
            save_json(args.output, report)
            print(json.dumps(report, ensure_ascii=False))
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
                    pixels = read_image(str(args.image))
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
                if not write_image(str(args.output), frame.pixels):
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
