# Master Duel アドバイザー

Windows 11 / Python 3.12 向けの**観測専用アドバイザー の開発基盤**です。画面を取得し、校正済み領域・画像テンプレート・ローカル OCR から状態を作り、画面上の候補に対する限定ルールで推奨を別 UI に表示します。ゲームへのクリック・キー入力、メモリ読取り、注入、通信解析は実装していません。

**現在の到達点:** Linux 上で合成画像、MP4 の録画再生、状態追跡、SQLite、候補生成、構造化 Decision、HTTP UI、評価を検証済み。実際の Master Duel 認識・Windows ライブ性能・完全な合法性判定・戦略判断は未検証／未完成です。合成デモの精度は実ゲームの精度ではありません。

## 環境構築

Linux クラウド（録画再生の開発）:

```bash
bash scripts/setup.sh
.venv/bin/python -m pytest -q
.venv/bin/python -m master_duel_advisor demo --output artifacts/demo
```

Windows 11（PowerShell、Python 3.12 を用意）:

```powershell
powershell -File scripts/setup.ps1
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m master_duel_advisor demo --output artifacts/demo
```

仮想環境の Activate は不要です。PowerShellでスクリプトの実行が制限されている場合は、`scripts/setup.ps1` の各コマンドをターミナルで順に実行してください。数値 OCR を使う場合はローカル Tesseract 5 を別途導入し、PATH に追加するか `TESSERACT_CMD` に実行ファイルのパスを設定してください。テンプレートのみのデモは OCR 不要です。API キー・外部モデル・サービスは不要です。依存は `requirements.lock` で固定し、Windows用dxcam/MSS/comtypesはOS条件付きで導入します。OpenCVはWindowsでは通常版、Linuxではheadless版を使い、同時導入しません。

## 録画再生とアドバイザー表示

```bash
.venv/bin/python -m master_duel_advisor run \
  --video artifacts/demo/recording.mp4 \
  --calibration artifacts/demo/calibration.json \
  --database artifacts/demo/cards.sqlite3 \
  --output artifacts/replay --realtime --loop --ui
```

Windows は同じ引数で `.\.venv\Scripts\python.exe` を使用してください。別のブラウザーから ローカルのポート8765の HTTP サービスへアクセスすると、現在の状態・推奨行動・対象・信頼度・理由・認識状態 が表示されます。クラウド環境セットアップ のプレビューリンクは使用しません。`--loop` はデモを繰り返し、周回ごとに履歴をリセットします。有限の録画再生 終了後に画面を残す場合は `--loop` の代わりに `--hold-ui` を使い、古い推奨は取り消して「情報が古くなっています」と表示します。終了は Ctrl+C。

出力は `latest.json`（最新状態・推奨・計測）、`events.jsonl`（観測差分）、`run.json`（処理数）です。キャプチャ内容には個人情報が映る可能性があるため、ユーザー指定の領域だけを保存してください。

## Master Duel との接続

接続は**表示中のデスクトップ画素の取得だけ**です。プロセスへの接続は不要です。

1. Windows で Master Duel を起動し、まずウィンドウ／ボーダーレス表示を使用します。
2. ゲーム内容のデスクトップ矩形 `left,top,right,bottom` を決めます。アドバイザーのウィンドウは取得領域の外へ置きます。初期実装は主モニターの正座標を対象とします。
3. `snapshot` で画像を保存し、[校正手順](docs/calibration.md)に従って実画面から領域とラベルを登録します。合成デモの座標・テンプレートは使えません。
4. 自分で付けた正解ラベル と別の検証画面で認識を評価します。実ゲームの精度ゲートを通るまでは信頼できる対戦助言として使用しません。
5. `run --rect ...` で取得し、別 UI を表示します。dxcam が失敗したら同じ矩形で MSS を比較します。

```powershell
.\.venv\Scripts\python.exe -m master_duel_advisor snapshot --backend mss --rect 0,0,1920,1080 --output data/screen.png
.\.venv\Scripts\python.exe -m master_duel_advisor run --backend dxcam --rect 0,0,1920,1080 --fps 30 --calibration data/layout.json --database data/cards.sqlite3 --output artifacts/live --ui
```

矩形は例です。実際の位置・解像度・DPI・モニター配置に合わせて調整してください。Windows Graphics Capture / OBS は未実装の比較候補です。独占フルスクリーン・HDR・画面切替等の対応を確認したとは主張していません。

## 評価とキャプチャ比較

```bash
.venv/bin/python -m master_duel_advisor evaluate --dataset data/holdout.json --calibration data/layout.json --database data/cards.sqlite3 --output evaluation/real-results.json
```

データ形式・精度ゲートは [evaluation.md](docs/evaluation.md)。評価は失敗時に終了コード1、設定失敗時に2を返します。`evaluation/results.json` は今回の合成データ評価です。

```powershell
.\.venv\Scripts\python.exe -m master_duel_advisor benchmark --backend dxcam --rect 0,0,1920,1080 --fps 30 --seconds 30 --output artifacts/dxcam-windowed.json
.\.venv\Scripts\python.exe -m master_duel_advisor benchmark --backend mss --rect 0,0,1920,1080 --fps 30 --seconds 30 --output artifacts/mss-windowed.json
```

同じ動きのある場面を対象にウィンドウ／フルスクリーンを比較してください。受領 FPS、意味のある画面更新率、読取り時間、CPU を測ります。GPU・真のフレーム落ち・物理表示から推奨までの遅延は追加の実機計測が必要で、未測定は null です。録画再生の高速処理率をライブ FPS と扱わないでください。

## 制限と次の検証

- 実ゲームの校正／ラベル付き画面／20–50種のカード参照画像がまだありません。
- テンプレート類似度 は簡易ベースラインです。透視変換・演出・UI テーマ・言語変化を一般化していません。
- OCR は2種類の前処理の一致と信頼度で棄却しますが、実ゲーム精度は未測定です。
- 未認識のゾーンは「空」になりません。隠れたカード、デッキ順、未表示の墓地一覧は推測しません。
- イベントは観測差分のみです。召喚・破壊などの原因は断定しません。
- ボタンの種類を候補にできますが、カード／対象の自動対応付け、包括的な効果ルール、戦略最適化は未実装です。Decision は候補内の信頼度優先のベースラインです。
- 段階4 の実ゲーム精度ゲート未達のため、カード認識の実運用移行と最終目標 は保留です。Windows 実機とデータを得たら 実行計画 の受入条件を順に検証します。

設計: [構成](docs/architecture.md) / [状態](docs/game-state.md) / [画面認識](docs/perception.md) / [カード認識](docs/card-recognition.md)。進捗と判断: [.agent/PLANS.md](.agent/PLANS.md)。
