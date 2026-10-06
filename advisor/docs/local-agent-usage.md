# ローカルエージェントの実行と検証

## 構成

[設計](local-agent-design.md)に責務と技術選定を記録しています。通常ループはローカル処理のみです。`--deck` はJSONの `name`, `card_ids`, `generic_card_ids` を読み、認識対象を限定します。IDはカードDBとテンプレートのラベルに合わせます。例: `{"name":"対象デッキ","card_ids":["13923"],"generic_card_ids":[]}`。これは設定形式の例で、完成したデッキリストではありません。

`--ui-rules` は `{"rules":[{"prompt":"duel_result","type":"CONFIRM","source_region":"action.result_ok"}]}` 形式です。promptとactionそれぞれの実画面テンプレートが必要です。未知の確認画面では操作しません。`ui.animation` にplaying/idle、`card_state.*` にface_up/face_down/selectable/selectedを校正できます。未校正は未知です。

`--plan-book` の各stepには `expected_cards`, `expected_prompt`, `expected_phase` を指定できます。カード条件は既存のrequiresと同じ形式です。期待した状態が確認できないと先へ進みません。演出だけの画素変化や候補の認識喪失を成功としません。手順と画面対応は[高速ループ](fast-loop.md)を参照してください。

## 起動

以下は完成した実対戦用設定ではなく、設定を用意した後のコマンド例です。リポジトリに `data/layout.json`, `data/cards.sqlite3`, `data/deck.json`, `data/ui-rules.json`, `data/plan-book.json` は同梱されていません。そのままコピーしても起動できません。`artifacts/demo` は合成画像用、実機検証の設定は限定した画面用であり、対戦全体の自動操作設定として代用できません。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m master_duel_advisor agent-loop --window-title masterduel --rect=-1920,785,-640,1585 --calibration data/layout.json --database data/cards.sqlite3 --deck data/deck.json --ui-rules data/ui-rules.json --plan-book data/plan-book.json --fast --ui --output artifacts/local-agent
```

dataのファイル名は利用者が校正する設定例です。位置・サイズ・DPIを合わせ、ゲームを前面にしてください。ウィンドウを移動・リサイズした場合は再設定して起動し直します。F8で一時停止／再開、F9またはESCで終了します。再開時は画面とプランを更新します。表示は `http://127.0.0.1:8765` の別パネルで、ゲームへの透過オーバーレイではありません。

毎認識の計測はperformance.jsonl、操作前後の状態・画像・入力と確認時間はactions.jsonlへ保存します。capture_read_msは取得呼出しの時間でFPS待機を含む場合があります。確認中のフレームはperceptionを直接呼び、個別性能行を出さず操作のverification_msに含めます。通常判断時間と演出・ディスク保存を含む操作全体時間を区別してください。

## グラフ・例外判断・教師データ

```powershell
.\.venv\Scripts\python.exe -X utf8 -m master_duel_advisor import-graph data/edges.json --database data/graph.sqlite3
.\.venv\Scripts\python.exe -X utf8 -m master_duel_advisor graph-paths --database data/graph.sqlite3 --source CARD_ID --target TARGET_ID --depth 4
.\.venv\Scripts\python.exe -X utf8 -m master_duel_advisor export-dataset artifacts/local-agent/actions.jsonl --output artifacts/local-agent/dataset.jsonl
```

辺はsource,target,relation,condition,source_urlを持ちます。SQLiteの限定深さ探索は関係の経路を列挙します。条件文から効果の合法性を自動証明したり、経路だけで操作を決めたりはしません。グラフを戦略評価へ接続する部分は残っています。

StrategyFallbackは任意providerを注入する非同期窓口です。構造化GameStateとJSON Schemaだけを渡し、期限・予算・盤面変化・現在の候補一致で応答を棄却します。APIキーを使わないSign in with ChatGPT providerとCLIを追加しました。[接続手順](chatgpt-connection.md)を参照してください。標準起動では外部呼出し0で、--chatgptが明示された場合にのみプラン枠を使います。実行済みサンプルのラベルは最善手ではなく観測した入力結果です。

## 実機で確認した範囲

artifacts/result-ui-validationに実対戦終了画面の参照画像・校正・入力前後の認識・validation.jsonがあります。OKの認識に続きComputer Useで1回クリックし、フリーマッチメニューへの遷移と旧候補消失を確認しました。同じ取得画像から作った参照の一致なので独立した精度試験ではありません。PythonのGuardedClicker、F8/F9とコンボ一式の実対戦受入試験は未完了です。

既存の3秒/60フレームの実画面計測では約19.7FPS、取得p95約19.08ms・認識約1.017ms・判断約0.147msでした。限定ROIの結果で、デッキ一式やOCR使用時の性能ではありません。`scripts/validate_live.py` のprepareは旧BATTLE画像を必要とするため、保存済みbattle-source-preserved.pngを使用してください。

検証コマンド: `python -X utf8 -m pytest -q`、`python -X utf8 -m master_duel_advisor demo --output artifacts/demo`、`python -X utf8 -m pip check`。実画面校正の再作成スクリプトvalidate_result_ui.pyは取得済みの対戦終了画像専用です。入力後の画像をそのまま使って再校正しないでください。
