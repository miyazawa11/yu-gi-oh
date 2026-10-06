# 目的単位の E2E baseline（2026-10-05）

## 合否の単位

ユーザー確認により「特殊召喚など一連の目的達成まで」を1アクションとする。素材・確定・表示形式・配置は子操作であり、34クリックを34標本にしない。今回の超雷龍ルートは混沌領域サーチ、ワイバースター特殊召喚、雷電龍サーチ、雷鳥龍による蘇生、超雷龍特殊召喚の5目的。未登録目的はunclassifiedで合格不可。

目標はcapture開始→目的結果の画面確認までaverage <= 3000ms、p50 <= 2500ms、p95 <= 5000ms、100以上の代表的目的、成功率 >= 99%、子入力の誤クリック率 <= 0.5%。操作正確性・安全性を先に満たす。計測のない最適化は行わない。

## 初期調査10項目

| 項目 | 現状 |
| --- | --- |
| 構造 | src/master_duel_advisorにcapture/perception/models/rules/decision/planning/strategy_rules/pipeline/agent_loop/safety。tests、scripts、data、config、docs、evaluation、artifactsが既存。全面移設なし |
| 画像取得 | capture.pyのLiveCaptureSource。MSS矩形取得またはdxcam同期grab。Frame.captured_atは受領時刻で取得開始ではなかった |
| 画像認識 | 校正ROI、OpenCVの縮小画像比較、領域キャッシュ、必要な数値だけ任意Tesseract。既存画像の縦横比を厳密検査 |
| 状態 | Pydantic GameState/Observation。公開カード、ゾーン、phase、turn、prompt、animation、facts、候補に信頼度と観測時刻。未知を実観測として埋めない |
| 行動決定 | 通常はローカルActionGenerator、RulePlanner、UI方針、DecisionEngine。明示設定の非同期LLM fallback。ルートは94戦略と別の34段階UI手順 |
| UI操作 | AgentLoopの校正領域中心座標→GuardedClicker。WindowsDesktopの前面・表示・移動・停止キー検査。Computer Use補助試験とは別経路 |
| テスト | pytestの単体/模擬統合、4場面合成demo、実校正監査、実画面preflight。合成成功を実機精度の証明にしない |
| 実機操作 | agent-loop。ただし校正監査で未対応ルートは開始拒否。手動補助Computer Useはassisted、無人KPIに含めない |
| 所要時間 | 正常な自律E2E標本は0件。従来observation_to_clickは結果確認まで含まない。operation_msは画像保存を含み、verification_msは内部認識とゲーム待ちを混合 |
| 3秒の阻害候補 | 現サイズと旧校正の不一致、ルート54校正項目不足により入力に到達しない。LLM往復、Tesseract起動、画像保存、poll周期は候補に留まり、最遅箇所の実測順位は未確定 |

## 初期実機preflight

証拠: `evaluation/baseline-tester/preflight-2026-10-05T13-53-41-417Z/preflight.json`。
ゲームのメニュー画面1280x720を取得。画面取得API約159.929ms、既存pipeline約0.8767msで縦横比を拒否（旧校正1280x800）。入力0、目的標本0、E2Eはnull。API取得時間をローカルMSSの実測と混同しない。この短い拒否時間は成功E2Eでも性能改善の根拠でもない。

## 計測実装

- `telemetry.py`のActionTelemetryとMeasuredCaptureで、同一の高分解能`time.perf_counter`時計を使用。既存の鮮度/判断期限のmonotonic時計とは数値を直接引き算しない。
- `capture_start/end`、`recognition_start/end`、`state_build_start/end`、`candidate_start/end`、`decision_start/end`、`coordinate_start/end`、`input_start/end`、`verify_start/end`と各spanを保存。複数回処理の外側start/end幅と、実稼働区間の和`stage_ms`を区別する。
- 画像再利用時は元画像の取得開始を維持し、確認処理の認識spanを二重登録しない。LLM待ちの再フレームも最初の判断cycle取得開始を維持。
- 成功時の`verify_end`は確認完了時刻。画像保存/JSON出力の後に置かない。失敗時は`verify_end=null`、`ended_at`と`verify_attempt_end`に終了時刻を保持。
- 親目的区間でspanを切り詰め、内部の重なるspanをunionして合算。結果確認のwall区間から内部計測を引いた値は`game_wait_estimate_ms`。ゲーム待ち、poll待ち、未計測Python処理の残差であり、サーバー/通信/演出の真因を観測した値ではない。
- `system_internal_ms`は計測した内部区間のunion。全Python処理を網羅した値ではなく、`unattributed_ms`を別保存する。性能改善量はまだ未測定。
- purpose結果は新鮮な`count.self.hand.<cid>` / `count.self.field.<cid>`の増加を求める。present=trueだけでは同名既存カードを新規結果と誤認するため不可。現校正はこのcount証拠も未対応。
- `logical_phase`は開始と異なる新鮮な目的phase、`logical_turn_advance`は新鮮なturn増分＋相手turnを要求できる。目的達成と次操作可能idleを同一視しない。既存の操作・確認ルールはこの計測追加では緩めていない。
- 入力例外、結果不明、中断、未分類を失敗側に残す。retryは実送信または送信結果不明の後に同じ入力を再送した場合のみ。候補再評価だけはretryではない。

## 正確な分母

初回認識失敗を省いて有効候補だけ100件集めることは禁止。`--benchmark-trials`で予定目的IDを画像取得前に登録し、capture開始で試行を開始する。取得失敗、候補なし、期限、停止でもその試行を残す。未開始の次予定は標本に数えない。非対戦画面のpreflightを試行数に水増ししない。

予定なしの通常ループもログを保存するが`admission=candidate_observed`の観測的ログとして扱い、baseline合格不可。試験予定は入力方針を変更しない。認識不能時に座標を推測して試験を強制しない。

既存`--max-actions`は子UI操作上限のまま。`agent-run.json`の`logical_actions`が目的件数。記録は以下。

- `logical-actions.jsonl`: 親目的、子step、入力座標/結果、各stage、状態差分、失敗理由。
- `telemetry-spans.jsonl`: 非操作/取得失敗を含む全計測span。
- `telemetry-events.jsonl`: abstain、認識エラー、fallback、停止など。
- `run-metadata.json`: 実行時ソースSHA256、校正/戦略/制限設定と各SHA256、Python/OS、時計精度、取得前の試験予定。異なる版/設定を同一条件の性能比較と扱わない。
- 従来の`actions.jsonl`と操作前後画像も維持。

## 集計

`benchmarks/README.md`のCLIを使う。live_autonomousだけがKPI母集団、synthetic/assisted/unclassifiedは別件数。成功E2Eと失敗を含む全attemptelapsedの分布を両方出し、欠測・未分類・予定外・100未満は不合格。誤クリックは子step_idに対する独立レビュー証拠が必要で、未評価を0%にしない。レビューは判定を変更するための合成ラベルとして生成してはならない。

目的categoryと子UI型coverageは別。子SELECT_CARD/YESNO等を目的件数へ加算しない。初期coverageは保守的な必要条件で、代表的な試験ケース・カード/先後/盤面分布の十分性は試験計画レビューで確定する。今回の2種類の目的（効果/特殊召喚）だけ100回繰り返しても全体KPI合格にはならない。

## 検証と未達

専用回帰はspan重複、完了時計、欠測、同名既存カード、phase/turn差分、画像再利用、LLM開始anchor、取得失敗、未送信retry、100件合否、未知誤クリック、候補ゼロのAgentLoop統合を確認する。ゲーム入力はこの実装担当では実行しない。実機E2E正常標本0、速度改善量null、最終目標未達を維持する。

## 本試験の事前固定cohort（2026-10-06追加）

`agent-loop --run-purpose`はpilot（既定）/baseline/acceptance。旧runやpilotの数値は参考統計として維持するが、100件でも本試験合格にはしない。acceptanceには`--benchmark-trials`、`--cohort-manifest`、`--cohort-slot`、`--execution-context`が必要。execution-contextはデッキ・ソロモード・試験画面等を明記するJSONで、全CLI実行条件とデータファイルhashとともに記録する。ゲームの隠れた状態をこの自己申告条件から推定しない。

本試験には`--offline-cards`も必須。オンラインのbackgroundカード取得は同じrunで知識が変化するため起動前に拒否する。必要な知識は事前にdatabaseへ充填する。offlineではcard-cacheをruntime知識として開かない。database/deck/plan_book/ui_rulesの参照ファイルは絶対pathと内容hashを事前固定し、capture前/入力直前にsize・mtime_nsの変化や消失を検出したらState failureとして停止する。終了時にも内容を再hashし、変更を検出したrunは`data_integrity=false`で本試験合格不可。毎フレーム全DBを読み直さない。size/mtimeを同時に意図的復元する変更は即時検出を保証せず、終了時hashで整合性を確認する。

manifestのschemaは`acceptance-cohort-v1`。`cohort_id`、`source_sha256`、`environment`（python/platform）、`runs`を指定する。各run slotは一意の`slot_id`、順序付き目的ID配列`trials`、`expected_fingerprint`を持つ。fingerprintにはcalibration/template_assets/stable_features/strategy/limits/capture/execution_conditionsそれぞれの`_sha256`を事前登録する。JSON hashはキー順を整えたUTF-8値のSHA256（telemetry.value_hash）。校正・route・制限値はカテゴリ別slotで異なってよいが、source/environment/cohortは全slot共通。baselineのmetadataで条件を確認し、最終source版が固定した時点でmanifestを保存・レビューしてから開始する。manifestは本試験中に変更しない。

実行は最初の画像取得より前に設定を照合し、run内に`run-metadata.json`と`cohort-manifest.json`を保存する。本試験出力は新規ディレクトリを使う。同じ出力metadataへの追記は拒否する。各ログ行にpurpose/cohort/manifest digest/slotを記録。集計は`e2e-benchmark ... --cohort-manifest <固定JSON> --reviews ...`で行う。全slotが一度だけ存在し、各slotの予定trial件数・目的・カテゴリ・順序がすべて一致し、metadataの各設定の値から再計算したhashも一致することを要求する。途中停止で未開始trialがある場合も本試験完了にはならない。良例のrunへの差し替えを許可する条件ではない。

manifestなし・未知metadata・pilot混入・異版・未登録の校正版・条件差・同slot複数runは`acceptance_cohort_integrity=false`。旧ログを移動してmetadataを失った場合も参考統計のみ。hash照合は整合性検査であり、後日の全証拠書き換えを暗号学的に証明/防止する署名ではない。事前レビュー済みmanifestと生ログを保管する。

時間の正規名は`measured_internal_span_ms`（計測内部spanのunion）、`verification_wall_ms`（確認wall）、`verification_residual_ms`（確認wallから重なる計測内部spanを除いた残差）。旧`system_internal_ms`/`input_after_verify_wall_ms`/`game_wait_estimate_ms`も互換値として保持。残差はpoll待機や未計測Pythonを含み、通信・演出の直接測定ではない。

誤クリック分母はinput_sent=True（確定送信）とNone（送信不明）を含む`misclick_denominator`。False（確定未送信）のみ除外し、確定送信数`input_count`と送信不明数`unknown_input_count`を別記する。`misoperation_rate`は誤クリックがあった目的の割合であり、意味的な誤判断の独立監査は未実装。予定trialでは入力なしfallback失敗も残るが、候補起点の未登録目的はその分母を保証できない。
