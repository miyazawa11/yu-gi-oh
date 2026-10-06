# Master Duel アドバイザー

カード原文はローカル優先で保存します。`run` / `agent-loop` は未保存のカードをYGOPRODeckから非同期取得し、保存済みなら再取得しません。英語原文・ID種別・取得元・日時・未加工JSONを保持します。[保存方法とルール](docs/card-knowledge-cache.md)を参照してください。

`agent-loop` の判断には10秒の期限があります。期限では、最新の許容候補から認識信頼度が最高の行動を強制選択します（勝率ではありません）。候補が確認できない場合は入力しません。詳細は[判断の10秒上限](docs/fast-loop.md)。

Windows 11 / Python 3.12 向けのアドバイザー開発基盤です。既定の `run` は観測専用です。明示して起動する `agent-loop` は、校正済み action UI を実クリックし、結果を再認識します。ゲームメモリ読取り、注入、通信解析は行いません。

**現在の到達点:** Windows上でローカル認識・差分キャッシュ・確認付きコンボ・入力ガードを実装しました。限定的な実画面取得性能と、対戦終了OKのローカル認識→Computer Use入力→メニュー遷移を確認済みです。Python常駐ループによるデッキ一式の対戦、実ホットキー、全カード認識、包括的な合法性判定は未検証です。合成デモの精度は実ゲームの精度ではありません。

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

観測は表示中のデスクトップ画素だけを使います。プロセスへの接続は不要です。

1. Windows で Master Duel を起動し、まずウィンドウ／ボーダーレス表示を使用します。
2. ゲーム内容のデスクトップ矩形 `left,top,right,bottom` を決めます。アドバイザーのウィンドウは取得領域の外へ置きます。MSS は負の座標を含む別モニターにも対応します。dxcam は主モニターの正座標を対象とし、別モニター選択は未対応です。負の座標は `--rect=-1920,785,-640,1505` のように指定します。
3. `snapshot` で画像を保存し、[校正手順](docs/calibration.md)に従って実画面から領域とラベルを登録します。合成デモの座標・テンプレートは使えません。
4. 自分で付けた正解ラベル と別の検証画面で認識を評価します。実ゲームの精度ゲートを通るまでは信頼できる対戦助言として使用しません。
5. `run --rect ...` で取得し、別 UI を表示します。dxcam が失敗したら同じ矩形で MSS を比較します。

校正済みボタンを反復して操作する場合は、`agent-loop` コマンドを明示して起動します。ESC で停止し、既定で300秒・100操作・信頼度0.98、同じ操作は連続3回までです。`game.terminal` 領域にデュエル終了表示の参照画像を `ended` ラベルで登録すると、その表示を高信頼度で認識して停止します。操作前後の画面と `actions.jsonl` を出力フォルダーへ保存します。実画面に対するクリック精度・UI配置・終了表示の校正は、実機評価用の独立データで確かめてください。

```powershell
.\.venv\Scripts\python.exe -m master_duel_advisor agent-loop --rect=-1920,785,-640,1585 --calibration data/layout.json --database data/cards.sqlite3 --output artifacts/agent
```

`agent-loop` の候補生成は既存の限定ルールを使います。戦略判断やカード効果の完全な合法性判定は行いません。信頼度不足では操作を控え、操作後に画像変化と状態または候補 UI の変化を照合します。結果が確認できない場合は再認識し、同じ古い座標を使い回しません。

`--plan-book data/plan-book.json` を追加すると、登録された展開の方針・次の手順を保持します。agent-loopは既定で待機0秒・確認周期0.05秒です（`--no-fast` で従来設定）。未変化領域の認識キャッシュ、操作確認画像と認識結果の再利用、非同期判断完了時の再判断、取得からクリックまでの計測に対応します。実画面の校正と手順登録が必要です。編集用の例と設定方法は [高速ループの手順](docs/fast-loop.md) を参照してください。1秒以内の実対戦操作は未検証です。

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

- 実画面の限定校正はありますが、1デッキ一式と全ダイアログの参照画像・独立した正解データは不足しています。
- テンプレート類似度 は簡易ベースラインです。透視変換・演出・UI テーマ・言語変化を一般化していません。
- OCR は2種類の前処理の一致と信頼度で棄却しますが、実ゲーム精度は未測定です。
- 未認識のゾーンは「空」になりません。隠れたカード、デッキ順、未表示の墓地一覧は推測しません。
- イベントは観測差分のみです。召喚・破壊などの原因は断定しません。
- ボタンの種類を候補にできますが、カード／対象の自動対応付け、包括的な効果ルール、戦略最適化は未実装です。Decision は候補内の信頼度優先のベースラインです。
- 段階4 の実ゲーム精度ゲート未達のため、カード認識の実運用移行と最終目標 は保留です。Windows 実機とデータを得たら 実行計画 の受入条件を順に検証します。

設計: [構成](docs/architecture.md) / [状態](docs/game-state.md) / [画面認識](docs/perception.md) / [カード認識](docs/card-recognition.md)。進捗と判断: [.agent/PLANS.md](.agent/PLANS.md)。

高速ローカルエージェント: [今回の設計](docs/local-agent-design.md) / [起動・校正・記録・検証範囲](docs/local-agent-usage.md)。

APIキーなしの例外戦略: [Sign in with ChatGPTのログイン・モデル選択](docs/chatgpt-connection.md)。

対戦知識: [調査索引・再利用手順](docs/knowledge/README.md) / [公式ルール進行](docs/knowledge/rules-and-turns.md) / [サンダー・ドラゴン](docs/knowledge/themes/thunder-dragon.md)。
