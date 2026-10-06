# 実行計画 — 観測専用 Master Duel アドバイザー

## ChatGPT本人ログイン後の実接続（2026-10-04）

ユーザーの「ログインしました」を受け、本人によるOAuth認証完了とplan_enabled=trueを確認。アカウント別モデル一覧を取得後、gpt-5.6-lunaで架空の接続確認状態だけを送信してJSON Schema応答を検証。APIキーなし、ゲーム入力なし。最初の応答でHTTP200だがContent-Typeが省略されたSSEを確認したため、ヘッダーが空の場合のみ本文のSSEフレーミング・completedを必須として処理するよう修正。無ヘッダーの非SSE、失敗・不完全・拒否・途切れた応答を棄却するテスト追加。成功した実通信の取得時間は約4209.8ms（モデル一覧を含む）、artifacts/chatgpt-inference-validation.jsonへ保存。通常ループへ待ち時間を入れず非同期Providerで利用する。

## 最新: APIキーなしのChatGPT接続（2026-10-04）

ユーザーの明示依頼に従い、公式Sign in with ChatGPTのローカルフローを実装。OpenAI Docsを確認し、dynamic登録、安定host ID、PKCE/S256、state/nonce、ループバックcallback、署名/issuer/audience/exp検証、別登録の分離、DPAPI保管、原子的更新・プロセス間ロック、トークン更新・失効処理を追加。既存のCodex/ChatGPT認証ファイルは読まない。APIキーは使用しない。

chatgpt-login/status/models/select/logoutをCLIへ追加。runとagent-loopの--chatgpt明示時だけ、選択したモデルを公式のアカウント別一覧と照合し、Responses HTTP/SSEへ構造化状態とJSON Schemaを送る。store=false/stream=true、completion必須、失敗/不完全/拒否/上限を棄却、非同期予算/期限/クールダウンを保持。通常のローカル操作はAPI待ちなし。曖昧な複数候補は外部戦略を待つ間クリックせず、既知UI/コンボを優先。プラン枠が使えなくてもAPIキー課金へ自動切替しない。

検証: Windows通常環境で全132成功・4スキップ。サンドボックスのDPAPI制約と一時フォルダー権限により専用basetempでテスト。日本語パスを含むbasetempで既存テストの直接cv2画像IOが失敗したため、実装と同じimage_ioへ置換して全件成功。合成demo4件は状態/行動一致1.0、実ゲームゲートfalse。pip check正常。認証情報なしの実discovery/JWKS通信成功、RS256公開鍵4件。artifacts/chatgpt-endpoint-validation.json保存。本人ログイン、モデル取得、プラン枠の実推論は認証完了前のため未検証。

PyJWT2.10.1/cryptography46.0.3と依存をlockへ固定。docs/chatgpt-connection.mdに起動・認証・複数登録・モデル選択・検証範囲を記載。認証コード/トークン/個人の認証URLはログ・実行計画へ記録しない。

## 最新: 高速ローカルエージェント（2026-10-04）

添付されたユーザー依頼を優先し、OS入力を許可された機能として開発。実装前にdocs/local-agent-design.mdで構成・技術・状態/行動/制御・性能・Phase 1受入条件を整理した。

- Phase 1: Windowsの前面ハンドル、現在のクライアント領域、取得範囲、他ウィンドウによる被覆、移動/リサイズ、F8 Pause/Resume、F9/ESCラッチ停止を入力前に検査。模擬デスクトップで停止/フォーカス切替時の入力抑止を検証。実終了画面からOKのprompt/actionを校正、ローカル認識CONFIRM confidence1.0、認識約0.438ms/判断約0.036msを確認。Computer UseのOS入力1回でフリーマッチメニューへ遷移し、別画面では旧候補が消えることを確認。artifacts/result-ui-validation/validation.jsonに保存。入力はsky経由で、Python GuardedClickerの実入力・実F8/F9・常駐ループ全体の受入完了ではない。同一画面校正なので独立精度ゲートは未達。
- Phase 2〜4/6: 既存の手札/ゾーン認識にdeck profile絞り込み、カード種別、表裏/選択状態、prompt/animation型、UI優先ルール、期待カード/prompt/phase付きコンボ中断を追加。未知UIは非操作。コンボ不在時は既存ローカル候補エンジンへ戻る。認識された変化でも低信頼度/古い値を成功に使わない。
- Phase 5: SQLite関係辺、出典/条件、upsert、サイクル回避・深さ/展開数制限付き探索、CLI import-graph/graph-paths。効果条件の解釈と自動戦略評価への接続は未実装。
- Phase 7: StrategyFallbackに構造化状態/Schemaだけを渡し、非同期poll、回数/期限/クールダウン、盤面変化棄却、最新候補との一致検査。Pipelineへ任意provider注入可能。標準起動はAPIなし。OpenAI adapter/CLI API設定・外部通信実測は未実装。
- Phase 8/9: 操作前後の状態/画像と処理時間をactions.jsonlへ、各認識計測をperformance.jsonlへ記録。確認成功分からstate→actionデータを出すCLI追加。最善手ラベルとは扱わない。ローカルHTTP表示に判断元/展開プラン追加。取得時間の計測をループへ接続。実画面の参照一式と独立ホールドアウト、デッキ全体の対戦と性能は引き続き未完了。

検証: Python -X utf8 pytest 109成功・4スキップ（Tesseract未導入）。合成demo4件の状態/行動一致1.0、実ゲーム精度ゲートfalse。pip check正常。グラフ境界/循環、デッキ絞り込み、学習ログ抽出、非同期プロバイダーの待機回避・予算・古い/非候補/期限切れ/Schema違反の棄却、UI優先/演出停止、期待状態中断をテスト。利用手順と実機限界はdocs/local-agent-usage.mdに記録。シミュレーター・ゲームメモリ・注入・通信解析は追加していない。

## 目標と制約

人間がゲームを操作し、システムは観測→理解→判断→推奨を行います。完了条件は Windows のライブ取得、実ゲームの LP・ターン・フェイズ・盤面・カード認識、共通処理による録画再生、履歴、対応範囲の合法候補、構造化された判断、表示、自動テスト、実測評価です。合成データだけで完了とは扱いません。

## 初期調査（2026-10-04）

開始時の `/workspace/yu-gi-oh` はファイル・コミット・依存関係・CI・指示のない空のチェックアウトでした。リモートにブランチがなく、指定の `main` もありませんでした。ホストは Linux / Python 3.12、Tesseract と FFmpeg は導入済みでした。Windows の画面と正解ラベル付き録画はありません。初期の決定的な実装に外部 API は不要と判断しました。

## 作業一覧

| 作業 | 目的 | 前提 | 受入条件 | 検証方法 | 状態 |
| --- | --- | --- | --- | --- | --- |
| 0 | 設計と判断の記録 | 調査 | コード作成前に文書を用意 | 文書確認 | 完了 |
| 1 | ライブ・録画取得と比較 | Python、ライブは Windows | 共通取得形式と時刻、10 FPS | 録画テスト、dxcam / MSS 実機比較 | 録画・定期取得を実装、実機検証待ち |
| 2–3 | 領域と型付き状態 | 0 | 縦横比、未知値、信頼度、認識元 | 座標・データ形式テスト | 設定した観測の範囲で完了 |
| 4 | LP・ターン・フェイズ | 校正画像と OCR | 実ゲームの各項目で95%以上 | 正解ラベルによる評価 | 基盤と合成検証は完了、実精度未検証 |
| 5 | 限定カード認識 | 20〜50種の参照画像 | 類似度と棄却、適合率・再現率 | 合成テスト後に独立した実ゲーム評価 | データ待ち |
| 6–7 | 追跡とカード DB | 型付き状態 | 保守的な履歴と SQLite | 状態変化・DB テスト | 観測差分は完了、原因付きイベント未対応 |
| 8–9 | 候補と判断 | 表示中の選択可能な UI | 対応候補だけを構造化して返す | 操作可能・不能のテスト | 基準実装は完了、カード・対象・効果・戦略未完成 |
| 10–12 | 表示・録画・計測 | 共通処理 | 別 UI、処理数制御、結果保存 | HTTP と録画の評価 | 合成データの接続は完了、実ゲーム検証待ち |
| 実運用 | 実ゲームで一連の動作 | Windows 11、ゲーム、校正済みデータ | 完了条件と性能の実測 | 実機受入検証 | 実機・データ待ち |

## 判断記録

- D001: Python 3.12、OpenCV / numpy、Pydantic を採用し、HTTP は標準ライブラリ、DB は SQLite とします。Tesseract は任意のローカル OCR です。
- D002: Windows の第一候補は dxcam、比較対象は MSS です。フルスクリーン等で失敗したら WGC / OBS を検討します。実測まで選択は暫定で、GPU・遅延の未測定値は null にします。
- D003: 校正は正規化座標と参照画像です。未実測の座標を検証済みと扱わず、表示範囲と黒帯を明示し、未知の配置から盤面を推測しません。
- D004: 初期ルールは表示中の校正済みボタンだけを候補にします。フェイズだけで召喚の合法性を断定せず、未知・古い情報では推奨を控えます。
- D005: 合成データは接続と手法の検証だけです。実認識の移行条件を満たすまでカード認識の実運用へ進まず、独立して進められる基盤を整備します。
- D006: 初期実装は LLM を使わず、API 回数・費用はゼロです。信頼度で順位付けし、操作実行は未実装です。
- D007: 校正・画面・再生出力はソース外または Git 管理対象外に保存し、画像を任意に自動取得しません。
- D008: Tesseract の強制3倍拡大で5200を9200と誤認しました。大きな画像は拡大せず、グレースケールと二値化が一致し信頼度0.90以上の場合だけ採用します。回帰テストは実ゲーム精度の証明ではありません。
- D009: dxcam の最新画像待機は静止画面で停止し得るため同期 grab を定期呼び出しします。画像がない場合を模擬テストし、実機検証は別途行います。
- D010: dxcam の依存に合わせ、Windows は opencv-python、Linux は opencv-python-headless に分け、cv2 の同時導入を避けます。OS 条件付き依存も固定します。
- D011: 小さな LP・操作 UI の変化を領域ごとに検出します。圧縮ノイズで処理が増える場合は実際の回数を報告します。
- D012: 実機検証はユーザーのローカル PC で行います。直接接続機能がないため ZIP と引き継ぎ手順を用意します。
- D013: 説明文・コメント・画面表示・メッセージを日本語化し、識別子・JSON キー・状態コードは維持します。画面上では日本語表示にします。

## 検証結果と残作業

`setup.sh` の導入・再実行と `pip check` は成功し、Tesseract 5.5.0 が利用可能です。合成4場面の状態・候補・判断は一致し、`real_perception_gate_passed=false` を維持しています。MP4 は12フレーム中5回認識し、4場面と差分を記録しました。合成データの平均処理時間は約1ミリ秒でしたが、実画面の遅延ではありません。API 回数・費用はゼロです。

HTTP 応答で表示画面、LP 8000、通常召喚の候補を確認しました。テストは古い推奨の取消、再生と履歴初期化、曖昧な画像、未知カード、古い観測、誤った正解、形式・座標、SQLite、OCR、Windows 取得の模擬を対象にします。件数と結果は `evaluation/development-validation.json` に記録します。

ZIP の新規展開後も環境導入・64テスト・合成デモが成功しました。これは Linux の可搬性で、Windows の検証ではありません。`install_script` / `start_skill` を保存しましたが、公開・新規タスクでの復元は未検証です。初期実装は `d4694fe` として GitHub の `main` へプッシュ済みです。

Windows の取得方式比較、独占フルスクリーン・HDR・複数モニター、実ゲームの正解、実カード、カード・対象の対応付け、効果の合法性、戦略は未完了です。最終目標を達成したとは扱いません。実機手順は `docs/windows-handoff.md` を参照してください。

日本語化後も64テストと合成デモが成功しました。JavaScript の表示変換、JSON の互換性、日本語ヘルプ、別ポートで起動した新しい HTTP サービスの表示・推奨理由を確認しました。


## Windows ローカル継続（2026-10-04）

ソースを親作業フォルダーの advisor へ新規展開。Windows 11 10.0.26200 / Anaconda Python 3.12.7 で隔離仮想環境を作成し、固定依存の導入と pip check に成功しました。Python ランチャーには登録がなく、setup.ps1 を PythonExecutable パラメーター（既定 python）へ変更しました。pip の cp932 読取り失敗は PYTHONUTF8=1 で修正しました。OpenCV の日本語絶対パスの画像読取り失敗はバイト列からの imdecode / imencode へ変更し、日本語パスの往復と合成評価の回帰テストを追加しました。

66件中62成功、4スキップ（Tesseract 未導入）。合成4場面は状態・候補一致、実ゲーム移行条件は false。録画は12取得・5認識。詳細は evaluation/windows-development-validation.json、合成評価は evaluation/windows-synthetic-results.json、テストは artifacts/windows-tests.xml。

ユーザー指定により画面取得は都度確認します。今回は取得していません。実ゲーム矩形・校正・独立ラベル・dxcam/MSS 比較・GPU/drop/物理遅延は未検証です。次回はゲーム画面取得の範囲と許可を確認してから snapshot を行います。


### 別モニター取得の継続

主画面の指定範囲はCodexだったため、モニター配置のみを照会。別モニターの左上は(-1920,785)、1920×1080。ユーザーからそのモニター左上の1280×720を1枚取得する許可を得て、MSSで実座標(-1920,785,-640,1505)を取得しました。制限環境では黒画像となり、通常権限の取得でMaster Duelの設定画面を確認しました。タイトルバーを含み、対戦UIは未観測です。

MSSのみ負の座標を許可し、CLIと取得処理を修正。dxcamの別モニター選択は未対応として負の座標を明示的に拒否。回帰テスト後は64成功・4スキップ。READMEの初期主モニター制限はMSSの対応範囲に更新します。追加の画像取得は都度確認し、次はユーザーが対戦またはリプレイ画面を表示してから取得・領域校正を行います。ライブ性能・実認識精度の検証は未完了です。


### 対戦画面の再取得

ユーザーの「再取得して」に従い、同じ矩形を1枚取得して artifacts/real-screen-004.png に保存。相手LP8000、Turn 1 / Main1、効果発動確認UIを目視確認。自分LPと下部ボタンは切れており、未確定とします。タイトルバーの高さを含む取得矩形のため、今後はゲーム内容を収める矩形を確認して再取得する必要があります。今回の目視ラベルを独立評価に流用せず、実精度ゲートは未達のままです。


ユーザー指定の別モニター相対矩形(0,0,1280,800)を実座標(-1920,785,-640,1585)として1枚取得。artifacts/real-screen-005.pngで両者LP8000、Turn 1 / Main1、手札5枚を目視確認。ゲーム内容は画像内y=31〜751付近と推定し、タイトルバーとゲーム外の下部を含みます。自動認識評価・校正完了とは扱いません。追加取得は引き続き都度確認。


### 反復型 Agent Loop 実装（2026-10-04）

ユーザー依頼により、既定の観測モードを保ちながら明示起動 `agent-loop` を追加。perception は認識済み action と `game.terminal` を返し、decision は既存の限定候補を使い、action は校正済みボタン矩形の中心をWindowsの画面座標へ変換してクリック、verification は画像差分に加えて状態または候補UIの変化を確認、recovery は操作失敗後に新フレームから再認識します。連続実行300秒、100クリック、信頼度0.98、同一候補再試行、同一操作3回、ESC停止を実装。全クリック前後の画像と actions.jsonl、run要約を保存。`game.terminal` に ended / active の独立したテンプレート校正が必要です。

Windows で66従来テストに加えAgent Loopの4テストを実行。合計68成功、4スキップ。pip check、合成デモ成功。信頼度不足時の非操作、座標変換、状態変化のない演出のみでは成功としない確認、終了表示時の停止を模擬で確認しました。実ゲームへクリックは行っていません。現状の校正データに実画面ボタンと終了表示テンプレートがなく、ライブ操作の安全な受入検証は未完了です。


### Agent Loop 再検証

ユーザーの「検証してみて」に応じて Windows 上で全テストを再実行し、68成功・4スキップ。pip check成功、合成デモ4/4状態・候補精度、実ゲームゲートfalseを再確認。agent-loop のテストは模擬Capture/Clickerを使い、校正座標へのクリック呼出し、クリック後の終了表示認識、画像保存、ログ、低信頼度のクリック抑止、画素演出だけで成功扱いしないことを確認。作業フォルダーには実画面向け校正JSONがなく、実ゲームのクリックは未検証。結果は evaluation/windows-development-validation.json。


## 対戦知識の記録（2026-10-04）

ユーザー希望に従い、次回以降の対戦時に先に `docs/knowledge/README.md` と該当テーマファイルを確認し、未登録テーマは調査して保存する規則を AGENTS.md に追加。公式 Master Duel 日本語サイトのチュートリアル/デュエルストラテジー、KONAMIの OCG/TCG Master Rules 説明、公式ターン進行ルールブックを参照し、`docs/knowledge/rules-and-turns.md` に記録。公式 OCG カードDBの雷龍主要カードテキストと公開デッキ例の「黄金櫃→雷電龍→雷鳥龍→超雷龍」基準線を照合し `docs/knowledge/themes/thunder-dragon.md` にまとめた。相手テーマを未公開情報から推測しない識別手順、調査テンプレートと索引を `docs/knowledge/` に追加。個別デッキリストは未提供のため混成型やMaster Duel現行採用枚数を前提にしていない。

## 展開の事前準備と高速ループ（2026-10-04）

ユーザーの自動操作・高速化の明示依頼に従い、初期の観測専用制約より今回の依頼を優先して既存agent-loopを拡張しました。`planning.py` にJSONの展開手順、公開カード条件、優先度、ターン内の完了済み手順、相手の公開ゾーン変更による再検討を実装。相手ターンでも方針を準備できます。プランモードでは現在の対応候補に一致する手順だけを選び、不一致は非操作です。進行は入力送信後の確認フィードバックによります。未登録の対面に一般的な戦略判断を行う機能やダメージ最適化はありません。

領域の画素が完全一致する時だけ認識結果をキャッシュし、現在の取得時刻で観測を生成します。ループには差分ゲート・確認画像の次判断への再利用・非操作画像保存の省略・高速モード（待機0秒、確認周期0.05秒、既定20FPS）を追加。待機後は認識と判断を再実行し、1秒を超えた観測では入力しません。未知への変化・候補の消失だけでは成功と扱わず、認識された変化を求めます。取得時刻からクリック呼出しまでの遅延とp95を記録します。Windowsで既存オフラインベンチマークのmonotonic時計が同一値を返しゼロ除算になったため、高分解能perf_counterへ変更しました。

検証: Python `-X utf8 -m pytest -q` は85成功・4スキップ（Tesseract未導入）。新規テストは手順の確認前進行禁止、未知/古い手札、相手盤面変化、対象不一致、ターン/終了リセット、キャッシュの時刻更新、認識喪失の成功判定禁止、古い画面の非操作、待機中終了時の非操作、高速モードの模擬クリック1秒未満とフィードバックを確認。pip check成功。合成デモは4/4の状態・候補一致、実ゲームゲートfalse（evaluation/fast-loop-synthetic.json）。実ゲームへの新しいループ起動は行っていません。サンプルは超雷龍召喚途中の編集用であり、実画面の全ダイアログ・位置・素材・表示形式に合わせたステップとカード/ボタン/終了表示校正、独立評価が必要です。実対戦でのクリック間隔1秒以内は未検証です。設定方法はdocs/fast-loop.md。

## 実機の限定ライブ検証（2026-10-04）

ユーザーのフリーマッチ開始・実機検証依頼で、現在のゲーム画面をComputer Useで確認。以前承認された別モニター矩形(-1920,785,-640,1585)のMSS取得は制限環境で黒画像だったため、通常権限を承認された上で取得しました。Draw・Main1・Battleの実画面から限定したLP・フェイズ・ターン側・超雷龍・カード選択UIの校正と1手のプランを作成。scripts/validate_live.pyで入力なしの3秒ライブ計測を2回実行。

初回は相手Turn3/Main1、自己8000・相手7800、超雷龍の画面で60枚/3.038秒、19.747FPS。p95取得19.077ms・認識1.017ms・判断0.147ms・合計20.362ms。自分LPと超雷龍を認識。未登録の相手の赤いフェイズ表示・ターン側・7800は棄却し非操作でした。該当参照を追加しましたが、その後対戦が終了し次の計測はフリーマッチメニュー。60枚/3.018秒、19.878FPS、合計p95 18.842ms、全項目未知・操作候補なしを目視と照合しました。追加した相手側の校正について新しい対戦画面での精度評価は未完了です。

入力は0回。新しいAgentLoopの実クリック・手順完遂・クリック間隔の実測は未完了。観測/認識/判断の計算時間をクリック間隔として報告しません。スクリーンショットはartifacts/live-validation、判断記録はevaluation/live-validation-findings.json。全テスト85成功・4スキップを再確認。実ゲーム精度ゲートはfalseを維持します。

## 起動設定の不足検査（2026-10-04）
利用者が設定例のdataパスをそのまま起動してSQLiteエラーになったため、build_pipelineで指定ファイル全件をDB接続前に検査し、不足パスを日本語で表示。利用ガイドに未同梱の例である旨を明記。元の起動コマンドで入力開始前の設定エラーを確認。通常ユーザー権限の全テスト138成功・4スキップ、合成デモ4/4成功・実機ゲートfalse。制限環境のDPAPI失敗9件は通常ユーザー環境で再実行して解消。実対戦一式の設定は未完成で、既存の限定校正を代用しない。

## ローカルLLM実装・実機接続（2026-10-04）
OllamaのループバックHTTP providerと--local-model/--local-urlを追加。ChatGPTと併用禁止、非同期予算・期限・最新盤面候補照合を再利用。リダイレクト/プロキシ無効、応答サイズ制限、completed/stop必須。番号・confidenceだけ生成し範囲検査後に元の候補へ変換。公式ポータブルOllama0.35.1とqwen3:4b-instructをプロジェクトtools内へ取得、hiddenバックグラウンドサーバー起動、start_local_llm.ps1と接続計測スクリプトを追加。RTX3060Ti8192MiBを確認、モデル3.2GB・100%GPU。単一合成候補テストは初回全文76秒、以降約1秒。番号方式は442ms/231ms/225ms/243ms/232msで5回候補一致。キャッシュが効く同一入力の接続計測であり実対戦判断精度やクリック速度ではない。全テスト148成功・4スキップ、合成デモ成功、実機精度ゲートfalse。画面校正・対戦全体の設定は未完成。

## ターン処理の待機と二重認識の削減（2026-10-04）

ユーザーの高速化依頼に基づき、既存agent-loopの固定待機・差分ゲート・確認後の認識経路を調査。高速設定をCLIとLoopLimitsの既定に変更（固定待機0秒、確認周期0.05秒）。--no-fastで従来値へ戻せ、個別指定を優先します。従来設定と比べ操作前の固定待機0.5秒を削除しますが、すでに--fastを使う場合はこの分の改善はありません。

非同期戦略のFuture完了時は静止画面の0.5秒更新期限を待たず、次の取得画像で通常の判断と照合を実行。確認した同一FrameのGameStateだけを次のPipeline判断に引き継ぎ、同じ画像の二重認識を省略。新規取得・入力停止時は破棄し、取得時刻・sequenceの不一致は拒否します。プラン進行・ルール判断は再実行。再利用時はperception_reusedを記録し、認識/OCR等の計測を重複計上しません。既存の鮮度・信頼度・終了・入力保護・操作結果確認は維持。

追加回帰テストは静止画面での戦略完了応答、確認結果の認識省略と判断継続、異なる画像識別子の拒否、既定の待機値。全テスト151成功・4スキップ（Tesseract未導入）。制限環境のDPAPI失敗と通常環境の一時ディレクトリ権限衝突は、通常ユーザー権限と新規専用basetempで解消。合成デモartifacts/turn-speed-demoは4/4状態・候補一致、実ゲーム精度ゲートfalse。ライブ対戦での短縮時間は未測定で、新しい対戦や画面取得は開始していません。

## 現行仕様の棚卸し（2026-10-04）
ユーザーの仕様・処理順・速度改善候補・ローカル知識の整理依頼に応じ、実装、CLI既定値、限定校正、保存済み評価を調査しdocs/current-flow-and-speed-review.mdへ記録。LLM再要求間隔30秒/実行5回、全画面差分による確認、小さなUI変化、同期PNG保存、OCRの都度起動を改善候補として整理。agent-loopのfps指定は周期制御に未使用、知識Markdown/カード関係グラフ/効果テキストは戦略判断へ未接続と確認。保存推奨情報を現行スキーマ対応と拡張対象に分けた。今回は文書のみ更新し、実ゲーム取得・入力・モデル呼出し・テスト再実行はしていない。

## 判断10秒期限と強制選択（2026-10-04）
ユーザーの最大10秒・間に合わなければ最高確率の候補を強制選択する依頼を実装。現行は勝率モデルがないため、説明した上で最新の許容候補の認識信頼度を順位として使用。認識開始からAI待ちまで共通の10秒期限を保持し、期限到達時は0.98以上・1秒以内の候補から決定的に選択。LLMのクールダウン/予算切れ/破棄済み処理中でも待たずに選択し、遅着回答を無効化。ワーカー増殖は禁止。OCRサブプロセスは残り時間を使い、runとagent-loopは期限を差分ゲートの例外とする。CLIのllm-timeoutは有限の0超10以下。forced_choice/decision_no_candidateと待ち込みdecision_elapsed_msを記録。候補なし、演出中、終了、古い観測は強制入力しない。10秒は判断期限でありOS処理のハードリアルタイム保証やクリック完了時間ではない。
通常ユーザー権限の専用basetempで全165成功・4スキップ。追加14テストは10秒境界、直前応答採用、最高候補、遅着応答、予算/クールダウン、OCR残時間、古い候補棄却、静止画面でも期限で模擬クリックまで到達を確認。合成デモ4/4・実機ゲートfalse（evaluation/decision-deadline-synthetic.json）。実対戦の入力は開始していない。

## 条件付きサンドラ展開ルール（2026-10-05）

「完全な展開ルール」依頼に対し、保存済み35種類を対象に94件の条件付きルールを作成。strategy_rules.pyとdeck-strategy-v1を既存--plan-bookへ接続し、通常初動、共有HOPT、誘発、カオス、融合、リンク、相手ターン、破壊代替、限定選択、素材確定を記録。毎回再評価し、未知・古い条件・未登録操作・操作確認中は非実行。通常の汎用判断、旧UIポリシー、LLM、10秒強制選択から条件拒否を迂回しない。旧plan-book互換は維持。カードIDはKONAMI CIDで統一。

GameStateに根拠付きfacts/material_sets、Perceptionにfact.*テンプレートを追加。materials.pyで個体重複、融合元と場所、リンク数と必要体数、効果/トークン/種族/名称条件を検査。手札雷族効果の発動と解決、共有使用制限と個別効果枠を区別。ドライバー通常召喚と剛鬼不在のデストロイ・オーガは基本戦略無効。35カードDB既存キャッシュを参照、公式の雷電/超雷/雷神/ヴェルテ詳細も照合。

全テスト200成功・4スキップ。合成デモ4/4、実認識ゲートfalse。新規テストで共有使用制限、条件未知/古い認識、重複候補、素材条件、優先度、モーダルUI、期限時の拒否迂回防止を検証。実画面取得・入力なし。詳細はdocs/thunder-strategy.md、全条件表はdocs/thunder-strategy-rules.md、実行JSONはdata/decks/thunder-dragon-review/strategy-book.json。

未完了範囲を明記: 効果使用/召喚制限の完全な履歴追跡、素材個体の自動画面抽出、全UI校正と対象選択、攻撃/ダメージ計算、全対面/チェーン裁定、実録画・実機受入。必要な事実を自動生成する機能がまだないため、完全自動展開とは報告しない。API原文やカード名だけからこれらの事実を補完しない。未認識条件はplan.blockedで見える。

## 暫定推測での展開継続（2026-10-05）

ユーザーが精度向上を後回しにし推測で進めることを明示したため、strategy-bookのinference_modeをprovisionalに変更。生成スクリプトも同設定を維持。未確認facts/必要カード/素材集合を認識済み登録操作に基づいて仮定する。実観測は変更せずplan.assumptionsへ記録し、deck_rule_inferredを表示。確認済みの不成立・素材不適合、未登録/古い/低信頼度操作、異なる/未知UI文脈、終了/演出/確認待ちは維持。10秒時にも同じ推測許容候補を利用。

送信済み発動/特殊召喚の使用枠、通常召喚、ヴェルテ後の特殊召喚禁止を暫定記録して繰返しを抑制。確認済みのターン切替/終了でリセット。操作失敗で使用枠を自動回復しない保守的な限界と、途中起動前の履歴が不明な限界を文書化。厳密モードstrictへ戻せる。全206テスト成功・4スキップ、合成デモ4/4・実認識ゲートfalse。実画面取得・入力は未実施。

## ユーザーデッキ画像の受領（2026-10-04）
対戦全画面対応用として提供された551×630のデッキ画像をdata/decks/thunder-dragon-review/deck-reference.pngへ保存。表示のメイン40・EX14と54枠の位置をinventory.draft.jsonへ記録し、枚数整合を検査。カード名を確定できる解像度ではないため全ID/名前はnull・needs_name_confirmationとし、実行用設定とは分離。追加のカード名資料が必要。実操作・コード変更なし。

## デッキ名・枚数の転記完了（2026-10-04）
ユーザー提供のテキスト表示画像から35種、メイン40枚（モンスター28・魔法9・罠3）、EX14枚、サイド0を転記。data/decks/thunder-dragon-review/deck-list.jsonとdeck-list.md、元画像deck-text-reference.pngを保存し、種類別合計をassertで照合。カードIDは未照合のためnull、実行用DeckProfileとは分離。画像の規制アイコンをMaster Duel現行規制として適用しない。対戦全画面対応には効果/ID照合・操作手順・対戦UI校正が残る。

## YGOPRODeckのローカル優先保存（2026-10-05）
ユーザー指定APIのv7仕様を確認し、card_knowledge.py、cache-card CLI、run/agent-loopの既定非同期補完を実装。共有SQLiteのknowledgeに英語原文・全カードJSON・URL・UTC取得日時・sha256・KONAMI/パスコード別IDを保存。保存済みは再取得なし、明示refresh、失敗1時間抑制、2要求/秒、単一ワーカー/最大64未完了要求。従来のCardDatabase単独・評価は通信なし。既存日本語名・校正IDを保存時に維持。APIは日本語未対応、Master Duel確認はfalseとして保持。AGENTSとknowledge索引へ未保存時の取得・保存ルールを追加。
デッキ35種すべてをAPIから保存し、同一KONAMI IDの公式ページタイトルと日本語名を照合。verified-aliases.json、deck-list.resolved.json、cards.sqlite3、deck-profile.jsonとsync-report.jsonを生成。元の転記は保持。通信を禁止した再読込みで35/35・追加通信0、メイン40/EX14を検査。全179成功・4スキップ、合成デモ4/4・実機ゲートfalse。記録はevaluation/card-knowledge-cache-validation.jsonとcard-knowledge-synthetic.json。取得した効果文を条件判定やLLM入力へ自動接続する変更は今回含めない。ゲーム画面取得・入力なし。

## 暫定ルールの画面補助付き実機テスト（2026-10-05）
ユーザーの実機テストと続行依頼によりComputer Useでゲームを操作。前半のフリーマッチで増殖するGとサンダー・ドラゴンを発動。中断後に別対戦（相手表示「滅びゆく世界」）を確認し、混沌領域→ワイバースター→雷電龍除外サーチ→雷鳥龍による雷電龍蘇生→雷電龍をリリースして超雷龍召喚まで完了。最終画面は自分Turn1/Main1、ワイバースターと超雷龍、双方LP8000。勝敗・無人完走は未検証。
validate_visual_assisted.pyによる8件の個別Planner評価をfree-duel-visual-assisted.jsonlへ保存。6件推測採用、増殖するGのchain.responseと超雷龍のextra.summon_selectの2件はprompt不一致で停止し、画面補助操作で進行した。自動認識・連続Planner履歴・10秒の実機期限は未検証。詳細と改善点はevaluation/live-provisional-test.md。今回はエンジン変更や全テスト再実行なし。実ゲームゲートはfalseのまま。

## 超雷龍ルートの段階別操作（2026-10-05）
前回提案への「お願いします」に応じ、RulePlannerへadditional_prompts、follows、observed_facts、expected_promptsを追加。増殖するGのchain.responseと超雷龍のextra.summon_selectを許容するが、未知promptを推測で許可しない。操作後の期待状態を確認したchangedだけでlast_completedを進め、未確認・失敗では進行しない。AgentLoopで選択factsの変化も検出。中断時のresetがRulePlannerに欠けていた点も修正し、UI進行だけを破棄して使用履歴を保持する。
scripts/build_colossus_route.pyとcolossus-route.jsonに混沌領域→ワイバースター→雷電龍サーチ→雷鳥龍蘇生→超雷龍の34操作を登録。位置は相対ゾーン名で定義し、画面校正に未検証の座標を追加しない。選択カード・枚数・場所・チェーン所有者・空きゾーンは暫定モードでも実観測必須。実画面の取得は前回の召喚完了盤面を1回確認したのみで、今回ゲーム入力なし。
既存の限定校正をaudit_colossus_route.pyで検査し54項目不足。evaluation/colossus-route-readiness.jsonに保存。段階付き手順の起動時にも同検査を実施し、不足したまま入力を開始しない。15種のprompt、動く手札の候補位置、選択factsの自動認識接続が未完了。無人実機完走・10秒実測・全画面対応の受入は未完了で、推測のtrue固定や補助操作で合格扱いしない。
新規15テストでは同一Plannerの分岐つき連続評価と実Pipeline/AgentLoop＋模擬入力34回の確認完了を検証。誤選択・未知選択・10秒強制選択による拒否迂回・期待状態不足・中断・使用履歴も検証。制限環境は既存DPAPIテスト9件失敗、通常ユーザー権限で全221成功・4スキップ（pytestキャッシュ書込み警告1）。最後の対象テスト41成功。合成デモ4/4一致、evaluation/ui-route-synthetic.jsonの実機ゲートfalse。ユーザーの途中質問にサブエージェントの利用と定義方法を説明したが、起動依頼ではないためサブエージェントは未使用。

## 実画面の既存認識テスト（2026-10-05）
Computer Useで現在のMaster Duelウィンドウを確認。目視は自分Turn1/Main1、双方LP8000、ワイバースターと超雷龍、手札4枚。実ウィンドウのスクリーンショットを保存し、タイトルバーと枠を除いた1280x720の画像を既存live-validation校正と実Pipelineへ投入した。
結果は縦横比不一致による認識拒否。既存校正は1280x800（1.6）、現画面は1280x720（16:9）。LP・フェイズ・盤面は未知、候補なし、推奨なし。ゲーム入力0回。実画面認識と自動操作の合格ではない。画面補助での過去の召喚成功と区別する。現サイズ用の領域・テンプレート校正と独立検証が必要。
成果: artifacts/live-screen-test-20261005/window.png、game.png、report.json。再現: advisorディレクトリで .venv/Scripts/python.exe -X utf8 scripts/test_current_screen.py。ソースエンジン変更なし、全pytestは今回は再実行していない。real_accuracy_gate=falseを維持。

## 試合終了までの操作依頼・承認サービス障害（2026-10-05）
ユーザーが試合終了までのゲーム入力と速度優先、不具合の開発・構成への追加を明示許可。Computer UseでMain1のフェイズボタンを操作し、フェイズ選択ダイアログを表示。先攻Turn1につきBattleは無効、Endが選択可能。
Endクリックは自動承認レビューのモデル容量不足で未実行。続く読取専用get_window_stateも同じ容量不足で未実行。安全性による拒否ではなく承認サービス障害。迂回操作をせず停止。ターン終了、試合終了、勝敗はいずれも未確認。
config/live-window-1280x720.observed.jsonへ現ウィンドウサイズ、内容切抜き、縦横比、目視UI位置、速度設定、未校正状態を記録。CLI実行用の校正manifestではない。最新観測なしの再クリックには使わない。エンジン修正・pytest再実行なし。

## 操作再試行の途中経過（2026-10-05）
ユーザーの再試行依頼で承認サービスが一時復旧。Turn1終了、相手のリバース・オブ・ザ・ワールドへ灰流うららを発動。Turn3でワイバースター1700と超雷龍2600の直接攻撃を確認し、相手LP3700。Turn4で終焉の王デミスの全体破壊に対し、超雷龍の破壊代替で墓地雷電龍を除外。超雷龍維持、ワイバースター墓地効果でコラプサーペント、雷電龍除外効果で雷獣龍をサーチ。相手LP1700、自己8000。
Turn5で墓地ワイバースターを除外しコラプサーペントを攻撃表示で特殊召喚。自己超雷龍2600とコラプサーペント1800、相手デミス2400。バトル移行クリックは承認レビュー容量不足で未実行。試合は継続中、勝敗未確認。
速度の観測: ツール往復に約0.2〜17.6秒のばらつき、容量不足待ちは30秒超。判断期限10秒やクリック間隔1秒の達成とは扱わない。全体破壊代替、任意誘発選択、サーチ選択、配置→コスト→表示形式の召喚UIを実画面で確認。画面の段階を固定順序と仮定せず、入力後の再観測で分岐する必要がある。

## 試合終了の確認（2026-10-05）
容量不足後に10秒待機し、読取再取得と同じバトル移行操作の承認が成功。Turn5、超雷龍で終焉の王デミスを攻撃し200ダメージ、戦闘破壊と相手LP1500を確認。その後コラプサーペントで直接攻撃し1800ダメージ表示を確認。続く取得はCONNECTING、次の取得はホーム画面。試合終了を確認し追加対戦は開始しない。WIN表示は未取得で、勝利は致死ダメージとホーム復帰からの推定として記録。
構成ファイルへ実測の画面段階、速度のばらつき、未達指標、改善バックログを追記。evaluation/live-duel-completion-20261005.json、artifacts/live-screen-test-20261005/post-duel-home.pngを保存。JSON再読込を検証。実エンジン変更なし、全pytest再実行なし。画面補助付きComputer Useの完了であり、agent-loopの無人完走と実認識合格には扱わない。

## 目的単位E2Eの計測準備（2026-10-05）

ユーザーが4役エージェント開発と平均3秒/100代表目的を要求し、特殊召喚等の一連の目的達成を1actionと確認。Researcher調査とTester preflightを先行し、メニュー1280x720が旧1280x800校正で拒否、入力0・正常E2E標本0を確認。詳細はdocs/benchmark-baseline.md。ソースの速度最適化は未実施。

Implementerが唯一のソース編集担当としてtelemetry.py、capture/Perception/Pipeline/AgentLoopの同一perf_counter span、目的/子step記録、事前試験登録--benchmark-trials、e2e-benchmark集計を追加。画像再利用とLLM判断cycleは初回取得開始を保持。source/校正/戦略/制限のhashをrun-metadataへ保存。認識失敗も予定目的開始後なら失敗分母に残し、通常の候補発生後ログはcandidate_observedとしてbaseline合格不可。未送信再評価はretryに数えない。fallback待機後に候補が出ない失敗もfallback率に含める。

34UI手順を5目的へ束ねるmetadataを追加。card presentだけで成功にせず新鮮なcount増分を要求。phase目標/turn増分を宣言する計測基盤も追加したが認識能力は追加していない。成功verify_endと失敗ended_at、成功E2Eと全attemptelapsed分布を分離。子誤クリック独立reviewが未知なら0%とせずKPI不合格。目的categoryと子UI型のcoverageを分離。

検証: 通常ユーザー環境で全241成功・4スキップ（最終fallbackフラグ1行修正前）。同修正と新規回帰を含む最終対象50成功。制限環境の既存DPAPI9件失敗、通常権限の共有pytest一時dir権限エラーは専用basetempで解消。新統合テストの10ms期限がOS時刻粒度で取得前に終了したため1秒上限へ修正、模擬終了画面で即終了。合成demo4/4、実認識gatefalse、compileall/pipcheck正常。ruff/mypy/pyright未導入でlint/typecheck未実施。

模擬AgentLoop34入力ログから5親目的を確認、CLI集計はunclassified5件を実機KPIから除外してsamples0・passedfalse。evaluation/telemetry-fixture-summary.json、telemetry-synthetic.json、telemetry-route-readiness.json、artifacts/telemetry-tests.xmlに保存。旧校正監査は引き続き34steps/54不足/structural_ready=false。操作正確性、3秒、100代表目的、速度改善量はいずれも実機未達。

## 限定phase認識の試作と独立失敗（2026-10-05）

Phase1の計測freeze後、Coordinator承認でphase-onlyの陽性複合証拠、限定監査profile、logical最終結果までの確認継続を追加。3つの実factテンプレート一致AND・最小confidence・競合unknown。Endbannerはphase ENDだけの結果証拠。source追加は限定認識の正確性修復で、速度改善と主張しない。カードrouteの合成stateは新鮮なcount正解を明示し、presentのみから成功にしない。

v1は正規化切抜きのfloor/ceil誤差で1pxずれを発見。生成ROIのepsilon補正だけで修正し同一性回帰を追加。独立044失敗を保存。v2は045を同じROIの訓練例へ追加、閾値.98固定、校正hash be737032831c29e15487b8113e03d4e7bd74a7099ed93b8b02dd4076729bd7bb。既存設計用000-028は通常/phase menu/End判別、危険なmodal/配置/演出/chain/相手turnは拒否。

新独立046でもclear_centerのみ一致、円とcard-menu境界が時間変動で不一致。自律入力0、未知停止。evaluation/phase-only-holdout-v2.jsonはpassedfalse。認識pass前にゲーム入力を開始しない。Researcherの変動分析待ち、テンプレート追加や閾値緩和を繰返さない。

全252成功4skip、対象60成功、demo4/4・実機ゲートfalse、compileall正常。docs/phase-pilot.mdに設計、固定版、失敗、read-only矩形検査、限定1目的起動コマンド、本試験案を記録。実機100目的/3秒未達を維持。

## 時間変動特徴v3と取得元差（2026-10-05）

Researcherが045/046の円.967285、左境界.877496、最適shift0,0を測定し発光変動と分類。Coordinator承認でstable_rgb追加。train047〜066の中央値prototypeと最大RGB偏差.01以下のmask、labelごと10枚以上/256画素以上、mask有効画素×3だけ平均。円589、左境界580画素。circle actionも同じ特徴で別票にしない。閾値.98/margin維持。参照PNG/prototype/mask hashを記録。

v3固定hash7b9c7773ec978aca9ae3d44544997fde35b5d51c3603f8b3bce94677769f7c06。新独立067はMAIN1/none .994897、phase_open .996934で認識合格。ただし通常権限MSSの実ゲーム画像は円を拒否、制限環境MSSは黒画像で全拒否。入力0、目的標本0。取得元の座標/DPI差をResearcher/Testerが切り分けるまでクリック禁止。

全257成功4skip、対象65成功、compileall正常。phase-v3-tests.xml、phase-v3-validation.json、phase-only-holdout-v3.json、phase-only-capture-source-v3.jsonとdocs/phase-pilot.mdへ保存。独立1画像成功・単一認識1.10msはE2Eや速度改善達成ではない。

## MSS sourceへ揃えた部分校正（2026-10-05）

前面MSSもSky訓練円を拒否。Researcher±2px比較は0,0最良、位置ずれを支持せず。TesterのMSS_TRAIN_v4 40枚から同じROI/feature/閾値でnormal専用版を生成、Sky template混在なし。circle923/edge912画素、訓練40/40、独立MSS_HOLDOUT_v4新3/3成功。normalhash2e2f38f6e7e1da069806f24e154edb338e4376390212ee47fe7891b0fe94898dを維持。

MSS_MENU_TRAIN_v4 20枚のmenu版を別フォルダーへ固定、前面独立MSS_MENU_HOLDOUT_v4_foreground新3/3成功。hashcefdee498ceb9dba3494db0d9d9118ad6fbfa8207edfd3dc46285ae5d667364c。非前面0/3取得ログも保持。Endバナー未収録なので目的END証拠を監査に必須化し、1不足で起動を拒否。全デッキ監査defaultは従来の54不足を維持。

監査修正後は全258成功4skip、sourcehash a6f0f7ffe6b8960a08a7c5000b3fb785f231e6252e6d4dcd0bfcebd2f13aa619。docs/phase-pilot.md、各training/holdout/readiness JSONに保存。自律入力0、目的0、E2E未測定。Endの同source資料が揃うまで自律全目的起動不可。


## MSS End限定完全版（2026-10-06）

明示目視ラベル0441/0443だけをMSS_END_LABELED_v4へコピーし、phase-mss-complete-calibrationを生成。hash170497ece4845f8b9ce69999eaba6e465016471745329f4d41d798c3ac1631dc。訓練END2枚一致、0434/0438/0440と黒画像はEND拒否、既存通常3/menu3認識維持。phase専用監査不足0、全34step不足54維持。evaluation/phase-mss-complete-v4.json。独立End0、自律目的0。新対戦Main1の独立MSS認識を待つ。ソース変更なし、前258成功4skipを維持。

新対戦（自分Turn2/Main1、LP双方8000、場空）の固定後MSS_COMPLETE_HOLDOUT_v1独立3枚も合格。AND .995478/.995356/.995313、MAIN1/self/none/idle、競合menuなし。evaluation/phase-mss-complete-holdout-v1.json。校正変更なしで限定1目的pilotの認識前提を満たした。End結果の独立目視検証は未実施。


## 初回自律pilot実測（2026-10-06）

`artifacts/phase-pilot-20261006T0012` の事前登録 main1_to_end が成功。フェイズメニュー→End→画面のEnd到達を1目的、子入力2として記録した。Testerは両入力を保存画像と座標で独立レビューし、誤クリック0/2。結果確認後に停止、再試行0、Fallback0。

| 指標 | 初回pilot |
|---|---:|
| 自律目的数 | 1 |
| 平均 / p50 / p90 / p95 / 最大 | 616.420 ms（同じ1標本） |
| 成功率 | 1/1（100%） |
| 内部計測の重複除去合計 | 146.442 ms |
| 画面取得合計 | 110.167 ms |
| 認識合計 | 15.953 ms |
| 入力合計 | 19.275 ms |
| 入力後確認のwall合計 | 470.285 ms |
| ゲーム待ち推定残差 | 364.131 ms |
| 未分類時間 | 105.846 ms |

確認wallと内部認識/取得は重なるので単純加算しない。ゲーム待ち推定は演出・通信を直接分離した値ではなく、pollや未計測Pythonを含む残差。内部で最大は画面取得、wallで最大は確認待ち。ただしこの1目的は目標に余裕があり、単発測定で速度最適化を増やさず、次の目的カテゴリの認識/正確性を先に検証する。

集計: `evaluation/phase-pilot-20261006T0012-benchmark.json`。全attemptと成功E2E両分布を保存。100標本・目的coverage・子操作coverageが不足し、総合 `passed=false`。pilotを本試験100へ混ぜず、代表カテゴリの100件と成功率99%以上の達成は未完。速度改善量は比較可能な旧版実機標本がないため未算出。


## 指定ゾーンの召喚目的（2026-10-06、実機未接続）

通常召喚の目的に `logical_zone_transition` を追加。例は side=self、zone=monster_2、card_id=12950、selected_card_fact=selection.card_id、placement_region=action.place。全段階で同じmetadataを使い、配置Actionは type=CONFIRM、target=self.monster_2 とする。これは計測の完了条件であり、操作を許可する認識ルールの代わりにはならない。

開始時の `zone.self.monster_2.occupancy=empty` がfreshなtemplate観測であること、途中で選択cardIDのfresh template事実が一致すること、対応source/targetの配置入力が実送信済みであること、さらに新sequenceで同zoneのfresh occupiedとcard由来CardIdentityが一致することを要求する。unknownゾーンは空ではない。選択/占有の推測fact、古い観測、未送信や送信不明、別zone/別card、同sequenceでは成功にならない。召喚成立後に別のチェーンpromptが現れても、目的の成立を確認できれば完了とする。

phase/count目的との互換を保持。特定通常召喚カードの校正/限定監査profileは未実装で、従来34stepの54不足を解消したことにはならない。最終全278成功4skip、対象56成功、compileall成功。新source SHA256は `7e64d1100a136e925ac3fcce55f49053103bc8823f6070050e17955b0ab1e9a5`。旧phasepilotのソースZIPをrun内に保存し、旧hashの実測と新版の合成検証を混ぜない。

TODO（本試験前必須）: cohort/pilot区分とsource/config/ROI/asset hashの同一性を集計側で検査し、異なる版のunionを拒否する。現summarizeは複数版を合算できるため、本試験判定にはまだ使わない。現レポートの単一版1pilotには影響しない。

追記（2026-10-06）: このTODOは下記の計測cohort整合性修正で対応。旧ログは参考統計を維持し本試験の合格対象から除外する。

Researcherレビューで、正配置後の別card選択を見落とす早期returnを修正。全履歴で最後の有効選択と対応配置だけを採用する回帰を追加し、最終全278成功4skip。


## 通常召喚の限定3操作版（2026-10-06）

MSSの適合済みinitial/menu/placement/post各20枚から、同位置の増殖するG（CID9455、ATK500/DEF200）を中央monster_2へ通常召喚する限定校正を生成した。600という途中目視値は誤りで採用しない。資料収集は補助操作で、通常召喚の自律目的標本は0。

`artifacts/normal-maxxc-calibration-v1` にcalibration.json、normal-route.json、trials.json、training-manifest.json。校正hash `eab254044b68585b0d0d3ad1881023f1873c412aeb127db2f8016657f26d851b`、routehash `7c178bb4922e069c3e16dbca800d98cb2ef387f4d7036edb0e7ae67dd729b7f2`。全ROIはclient座標。hand_layoutは局所slot輪郭(409,615,22,105)で、他4枚の内容や汎用手札枚数5を推定しない。対象カード画像と通常盤面の陽性ANDが揃う場合だけ候補になる。

normal_summon監査はSELECT_CARD→NORMAL_SUMMON→CONFIRMの3操作に限定。宣言CID、self/Main1、同目的/同zone、follows、期待prompt、配置source/target、実選択/召喚有効/局所手札文脈を検証する。turn不明を補完せず、通常召喚使用履歴も固定しない。目的の占有empty/occupiedとfieldCID画像まで揃わないと監査を通さない。全デッキの54不足はそのまま。

訓練80枚では初期none、menu card.menu、placement placement.select、post occupied+field9455を確認した。postのprompt/phaseはunknownであり、都合よくidleを固定しない。_verifyは最終logical目的の全肯定証拠＋画像変化＋新sequence＋planner期待が揃えば、直前unknown→結果knownでも目的成立を確認できる。未送信/送信不明、同画像、planner拒否は成功にならない。既存非logical経路とphase確認の回帰も維持。

旧Sky000〜071の72探索負例で開始誤許可0、ただし独立評価ではない。新postと別対戦同位置Maxxの独立holdoutが必要。全304成功4skip、対象97成功、compileall正常。sourcehash `0f6ef470e7a0395c9672b961a63b21c1a8098fc859cf223b85726bd44980d1e4`。前zonegoal sourceは `artifacts/normal-zone-goal-source-7e64d110.zip` に保存。normal-profile-validation.json/normal-maxxc-training-v1.json/normal-maxxc-old-negatives-v1.jsonへ証拠を保存した。

## 本試験cohortの計測整合性（2026-10-06）

telemetry/CLI/agent_loopのみ最小変更。run-purposeはpilot/baseline/acceptance、既定pilot。acceptanceには事前固定cohort manifestと一意slot、予定trial、実行条件JSONを要求。source/Python/platformは共通、校正・ROI・template資産・stable特徴・route・制限・capture・実行条件はslot内でhash一致を要求する。カテゴリ別slotの校正差は事前登録すれば許容。画像取得前に照合してmetadata/manifest snapshotを保存し、同出力の再利用を拒否。集計は全slot、一度だけのrun、全予定件数/順序/目的/カテゴリ、設定の実値再hashを要求。pilot/旧unknown/異版/欠測の参考統計を維持し、本試験合格不可とする。合成100件gate回帰は実機性能・レビュー証拠として扱わない。

時間はmeasured_internal_span_ms/verification_wall_ms/verification_residual_msを追加し旧keyを互換保持。残差はゲーム待機の直接実測ではなくpoll/未計測Pythonを含む。unknown送信を独立レビュー分母に含め、確定送信数とunknown数を別表示。意味誤判断の独立監査、候補起点の入力なしfallback目的分母は未対応。予定trialでは入力なしfallback失敗を残す。

検証: `python -X utf8 -m pytest tests/test_telemetry.py tests/test_agent_loop.py tests/test_integration.py -q` 最新90成功1skip。全suiteはsandbox315成功9失敗4skip（DPAPI credential_protection_failed）、通常ユーザー環境かつ新規project basetempで324成功4skip。その後追加した取得前snapshot/出力重複拒否の1回帰は対象suiteで成功。全suite通常環境にpytest cache書込権限warningあり、テスト結果への影響なし。初回UTF8指定なし対象suiteは既存read_textのcp932復号で6失敗、-X utf8で解消。compileall成功。ruff/mypy/pyright未導入のためlint/typecheck未実行。evaluation/measurement-integrity-{tests,host-tests,targeted-tests}.xmlに検証記録。

旧baseline（evaluation/baseline-tester/baseline-20261006T0120）の再集計は平均/p50/p90/p95/max623.4106000047177ms、成功1/1、誤クリック0/2を完全維持。旧metadata/生ログは変更せず新evaluation/measurement-integrity-baseline-reaggregation.jsonへ出力、acceptance false。速度改善量は未測定。この修正は集計の正確性であり高速化ではない。source SHA256 `c2bd92e3653fbe8cd12daf1fa912ce55d8de512888495379cd639a705c1b0305`。新sourceでの実機テスト/100代表目的は引き続き未達。

最終レビュー追加: acceptanceは--offline-cards必須としてpipeline/DB初期化前にonlineを拒否。事前充填databaseと参照deck/plan_book/ui_rulesをpath/content hashで固定。capture前と入力直前にsize/mtime監査し、変化/消失でState failure停止。終了時content hashを再照合しdata_integrity=falseのrunは本試験不合格。offlineはcard-cacheをruntime知識として開かない。size/mtime同時復元の意図的変更を即時検出する保証はなく、終了hashで検出する。最新対象91成功1skip、compileall成功。最終source SHA256 `d0afd41ea9e6222c3c48bebc75b3cf3e58cb7d6f47ea86037d92c823567d787c`。

最終全suite（`python -X utf8 -m pytest -q -p no:cacheprovider --basetemp=artifacts/measurement-integrity-host-temp-v2 --junitxml=evaluation/measurement-integrity-host-tests.xml`、通常ユーザー権限）は326成功4skip、15.39秒、warningなし。対象suiteは91成功1skip。実機操作/新source実機成功の主張は行っていない。

## Solar局所slot2通常召喚profile（2026-10-06）

既存scripts/build_normal_calibration.pyを明示profile化（maxxc/solar-slot2/solar-slot2-v2）、3rule構造とruntimeは維持。G9455のcalibration/route/trialsは実資料で再生成して元ファイルとbyte完全一致。SolarはCID13581、手札局所slot2、初期は隣slot3孤高hoverという固定画面配置。汎用7枚手札対応とは称さない。fieldCIDは中央実field上部(609,404,61,45)、occupancyは(603,398,74,53)のみ。modal内カード絵を証拠にしない。postのphase/prompt/turn/hand_countはunknownのまま。入力なし検証helper scripts/evaluate_normal_profile.pyと合成generator回帰tests/test_normal_generator.pyを追加。

v1は80/80訓練合格、確認済み負例88/88で開始/結果誤認0。しかし固定後post3枚は0/3、Recognition failure、CID約.93369/occupied約.94175。±4px探索は(0,0)最良、相手field art .99996/modal art1.0だが自field art .91698で局所色変化が大きい。通信/取得元差/座標ずれは根拠薄く、描画機構を断定しない。v1はhash cbe7823eabe83a93410ad9612810d94a0263dec4fedb34c754b964a54170cd72として失敗版を保持、自律使用禁止。

時間分散の追加post11枚（10.098秒）と旧20枚を合わせるとstable maskはoccupied304/CID72で、CIDの最低256要件を満たさない（solar-normal-margin-v2.json）。閾値や最低画素を下げず、title/枠だけへCIDを弱めず、v2は新安定post11枚で同ROIを学習。初期/menu/placement各20+post11の71/71訓練合格。旧青白post20/20は未対応過渡として確認待ちであり、未成立/誤操作と断定しない。旧v1失敗holdout3は訓練に入れず既知診断資料として3/3認識（独立精度に含めない）。確認済み負例88/88で開始/結果誤認0。初回530枚探索は未分類画像を含むため正式負例評価に採用せず、Researcher/既存目視ラベルが確実な88枚へ修正した。

v2 CID正例最小.999985/負例最大.758908（差.241077）、occupied正例最小.999954/負例最大.793933（差.206021）、両mask2048、閾値.98維持。固定後の新post3枚はTester評価3/3、occupied.999973〜.999980/CID.999990〜.999995、input0/E2E0。新対戦initial/menu/placement適合、実入力から安定表示への移行とtimeout適合、空field+chainの確実な負例画像は未検証。速度改善量は未測定。

v2固定artifacts/solar-normal-calibration-v2/{calibration.json,normal-route.json,trials.json,training-manifest.json}、calibration hash4d82031330e6b67d7eccdf947a00eb60c506419508ec368bd9f8380811bece3f、route hash117b3ecff37e5f86543d58709fe924f5fcce55d018ce71b455d045af997dac61。evaluation/solar-normal-{training-v2,negative-v2,transient-wait-v2,known-diagnostic-v2,margin-v2,post-holdout-v2}.json。詳細/コマンドdocs/solar-normal-profile.md。

最終検証: 対象109成功（normal_generator/normal_profile/telemetry/agent_loop）、全332成功4skip（通常ユーザー環境、python -X utf8 -m pytest -q -p no:cacheprovider --basetemp=artifacts/solar-normal-host-tests-v2 --junitxml=evaluation/solar-normal-host-tests.xml）、compileall成功、v2 build_pipeline初期化/3rule構造監査成功。lint/type checker未導入。runtime sourcehash d7c39a500acc6d9ef56f1852ed849b08a371a030fab2fe2efcf01fd852944897（Coordinator依頼のtelemetry集計文言修正を含む）、generator hash8617817a9b0b97f136ac2cb1a78f17be9578efa4ddbaca505d85de5ea3ff2d4c、helper hashf57d22d7dd2fd94a22167607c9e0fc8db9080d0353c939dd594ebfc55fa39d91。

## 選択詳細名レジストリ（2026-10-06）

Coordinator許可範囲として新detail_name_registry.py、build/evaluate helpers、3CID assets、tests/docsだけを追加。既存cal/strategy/action/UI/telemetry変更なし、認識ライブラリをpipeline/GameStateへ接続せず、CIDは詳細表示内容のみ。毎フレームstateless evidenceで、unknownに古いCIDを残さない。固定ROI[24,106,217,24]/1280x720 BGR uint8、64x32特徴、score.98/margin.03を保持。schema/source/namespace/shape/feature/hash/3CID検査。固定registry SHA86e6cc60a004b0d8aff769bd6ee0b0d8c0653f136199cae9af612e47babd6950。

旧探索43正例/32負例=75/75、falseCID0。formal independent holdout未実施。局所recognition7500calls平均.052911/p50.03675/p95.1283/max.7772ms（画像load除外、E2E/入力0）。unit+旧画像integration11passed。固定path/CLI/hashをCoordinatorへ即通知、Tester新資料待ち。offline evaluator mode/source/時刻不明0/manifestindexを明記、usable_for_input=false。詳細docs/detail-name-registry.md。全回帰351passed4skip38.03秒（通常ユーザー環境、python -X utf8 -m pytest -q -p no:cacheprovider --basetemp=artifacts/detail-name-host-tests-v1 --junitxml=evaluation/detail-name-host-tests.xml）、後のoffline証拠追加testは局所11passedで確認。compileall成功、lint/type checker未導入。source SHAac8d0752039ffc64b38bcf9744a417c231a6853b66ae45d0c5ae75e8f038491f（新未接続moduleの追加のみ）、hash一覧evaluation/detail-name-fixed-hashes-v1.json。初回調査/baseline統合はCoordinator作成docs/baseline-research-20261006.md参照。

## ローカル名前OCRの最小実験（2026-10-06）

src/runtime/既存cal/telemetryは変更せず、新scripts/benchmark_card_name_ocr.py、局所unit、data/ocr、evaluation、docsのみ追加。既存Tesseract5.4.0.20240606のbinaryを絶対pathで使用。日本語model不足を解消するため公式tessdata_fast/docs確認後、commit87416418657359cb625c412a48b6e1d6d41c29bdのjpn.traineddata（2471260bytes/SHA1f5de9236d2e85f5fdf4b3c500f2d4926f8d9449f28f5394472d9e8d83b91b4d）とApache2 LICENSEをプロジェクト内data/ocr/tessdata_fastへ取得。source.jsonにURL/日時/commit/hash。sandboxのsocket拒否は公式file取得だけ通常権限で解消。ProgramFiles/PATH設定変更なし、外部画像送信なし。

局所main名前行のraw3x/PSM7/OEM1/jpn→TSV→DB日本語名。NFKC/空白除去以外の文字補正なし、partial/fuzzyは拒否、同名複数CIDも拒否。初回tsv config未同梱のstderrを確認して、-c tessedit_create_tsv=1へhelper修正。初回失敗ログは保持しmodel精度と扱わない。train上だけ少数のgray/otsu/raw2/raw4/PSM13を試し、raw3/PSM7/.90実験confidence gateを固定。Tesseractconfidenceは未校正、成功確率99%やRGB.98と同じ尺度とは扱わない。

G/Solar各5train/15eval、新Driver/Ash/雷電龍first各3train/reopened各3eval。39eval画像/117callsで全名exact26/33=78.79%、CID採用8/33=24.24%、partial6/6安全棄却、誤CID0。Gexact9/15/採用8/15（末尾ノイズ6/低conf1）、Solarexact14/15/採用0（低conf14/誤字1）、Ashexact3/3/採用0（低conf3）。Driver/雷電龍scroll partialはblankとしてunknown。postの無い名前欄を無理にOCRせず、全画面OCR/毎ActionOCRを導入していない。

時間は初回185.163ms、平均176.448/p50177.377/p95185.600/max200.160/反復平均176.690ms。ROI/PNG1.696、process起動/model読込/OCR174.636、parse/alias0.116ms。画像ファイル読込/復号・画面取得は対象外。物理cold cacheや常駐engineの性能とは称さず、同画像反復を独立精度標本として加算しない。G/Solarは同burst画像分割、新資料は方式固定前の後刻reopen分離なので正式独立holdoutとは称さない。現採用率ではruntime統合不可、画像template第2証拠は将来候補に留める。

評価/ログはevaluation/card-name-ocr-{manifest-v2,fixed-settings-v1,fixed-train-v1,fixed-eval-v1}.jsonと全call JSONL、詳細docs/card-name-ocr-experiment.md。unit9成功、実Tesseract固定train/eval174callsでintegrationを検証、compileall成功。最終全suite341成功4skip、33.31秒（通常ユーザー環境、python -X utf8 -m pytest -q -p no:cacheprovider --basetemp=artifacts/card-name-ocr-host-tests-v1 --junitxml=evaluation/card-name-ocr-host-tests.xml）。lint/type checker未導入。runtime source SHAはd7c39a500acc6d9ef56f1852ed849b08a371a030fab2fe2efcf01fd852944897のまま、OCR helper SHAd7893aa7fe01ebbb3b33aab80a7609c305bd04181dfa3ca1f854b80f91aee880。入力/E2E0、速度改善msは未測定。

## A1召喚候補位置の証拠（2026-10-06、入力未接続）

Coordinator承認の新action_evidence.py/evaluator/tests/config/evaluation/docsだけを追加。既存runtime/Action/cal/3rule/LogicalZoneTransition/safetyは未変更。局所探索±64x/±24y、4px粗→±3px精、旧stable_rgbのscore.98/位置margin.03固定。別位置のrunner-upと種類競合を分離、Special/Flip/無効は未検証、usable_for_input=false固定。CID/zone/クリック点を生成しない。offline=0/manifest indexとlive実monotonic/sequence/client矩形を明示し、保存画像のnowによるfresh化を拒否。asset stat変更/評価前後fullhash、関連modulehashを保存。

40train+目視no-button4画像×2profile8照合+SET2crop=50cases/44unique画像で全一致。反復144calls探索平均33.407ms/p5033.275/p9035.328/p9535.902/max40.309、同一入力固定ROI平均.186ms、追加約33.221msのcoverage基盤で高速化ではない。固定後Ash新3枚は採用3/3、最小score.996274/margin.237895、平均33.087ms。ただしbbox独立原点未確認3枚、joint_position_passed=false。別対戦/種類全体/目的E2Eを称さない。

unit初版27passed、bbox未検証分離を含む最新全回帰は通常ユーザー環境380passed4skip41.81秒、sandbox370passed9failed4skip(既存DPAPI credential_protection_failed)、compileall成功、demo4/4実機gatefalse。ruff/mypy/pyright未導入。evaluation/action-evidence-{unit,all,host}-tests.xml、exploration/ash-holdout-v1.json、fixed-hashes-v1.json、docs/action-evidence.mdへ記録。source6c9116cafe0c297f530608b0e4b2ec21831fc9abc059c544e468511a78fdc979、module8c818d99c8b3da29d9b2b34e78b42234b58d6fe4d7cc91ce7f7907beb2570032、設定38ac24d4a30f0606a8d46cd4c1dfcf16c1289cf6528f8c5e844a434867f38e1f。既存source(新module除外)ac8d0752...完全維持。A1入力0/E2E0、100代表未達。

CoordinatorがA2のAsh menu開始→normal→指定zone配置→実zoneinspect/detailCID結合の別profile実装と、Tester1回補助召喚の収集を承認。独立3枚は訓練流用禁止、旧profile/fieldCID条件は緩めず、actual input receipt/newseq/highlight/empty→occupied/CID/正しいnormal種別をANDしてから実機pilotへ進める。別補助対戦で中間画面を全部先取りすることは絶対前提にせず、freshguardで未知中間は失敗を記録して安全停止。

## A2限定Ash正常召喚→中央配置→実zoneinspect（2026-10-06）

Coordinator承認の既存runtime最小分岐（models/regions/perception/strategy_rules/route_validation/capture/safety/telemetry/agent_loop/cli）、新builder/preflight/unit/docsのみ単独所有。旧normal_summonとcard:fieldCID経路を維持。実資料でhighlight差は未確定のため、別LogicalInspectConfirmationはpanel明示blank→zone内実入力→新seq Ash詳細出現を採用。開始detail/hand輪郭/有効normal UI/empty、自分Main1/active/idle、実正常召喚/同zone配置/occupied/actual inspect/clock/client/epoch/assetをAND。Turn/枚数/LPを偶然固定せず、通常召喚履歴unknownを0へ書換えない。saved取得はliveへ昇格しない。未知中間は新profileで停止し、再試行0のpilotを予定。

ASH_NORMAL_INSPECT_TRAIN_v1_20261006のmenu/placement/post-unselected/post-inspected各10MSSを使用、独立A1 Ash3枚は不使用。post-transition104枚は配置前の手順失敗で除外。assisted sky receiptはruntime送信済fixtureへ変換しない。訓練40/40、入力0/E2E0。新unit60成功2.24秒、既存normal/telemetry/loop153成功3.59秒。全sandbox431pass9fail4skip42.95秒（全9既存DPAPI）、host440pass4skip43.74秒、final freshness guard後host再検証はevaluation/inspect-host-tests-v2.xml。compileallとdemo4/4成功、実機gatefalse、lint/type未導入。

取得由来live_mss/実rectを追加、新限定動的UiCoordinateProofをsameframe/source/hash/bbox/ageで確認。GetLastInputInfoはsession活動の不透明tokenで同tick等見逃しあり、全外部入力不在の完全証明ではない。既存mouse_event backend呼出完了をinput_sent=Trueと記録するがOS送信数/ゲーム受理証明とは称さない。visual goal+epoch+独立点/結果レビューで別途成功判断。新cal/route/asset/sourceをrecognition_componentsへ固定、変更を入力前/終了時に拒否。

固定UTC2026-10-05T18:38:20.719769+00:00、source0192ffc2ac4d7d787a5ad6eb04412a7774d21fe73cc68918383ed3103afd9e76、calfbb11ef8453142247a957dd3dedb61efe50acd2745dc290a481d6a6b633e72b6、route2caacbd58fb731bcea385bba491aa050bf142b642c20f395e17280f00ef5c217、componentsf174d1c8962fec995a145ee05538594d483927c68abb08d5e321617ab8f6b1d6。evaluation/normal-inspect-fixed-v1.json。Testerへfresh no-input preflightと最大3input/15s/再試行0/登録1目的pilot commandを通知。新Turn2/手札6Ash開始画面は訓練流用せず固定後に診断予定。速度改善は未測定、100代表未達。

A2 v1固定版のfreshpreflightはinput0安全棄却。normal最大全探索局所score.976373/margin.183008、中央empty.978574、固定輪郭.854690で.98未達。coverage不足をCoordinatorへ報告し、閾値を下げない新限定layout v2追加を承認。失敗画像は未訓練。Tester別新MSSmenu10枚（ASH_NORMAL_INSPECT_LAYOUT2_TRAIN_v2_20261006）から、新normal実crop338,502→公称探索anchor380,497へ正規化したA2専用参照と相対輪郭365,584→407,579を校正。旧placement/post30維持、v1/A1資産は不変。RGB.98/位置margin.03/最低256pixels維持、追加runtime source/moduleなし。機械profile名solar-menu-v2は有限探索I/F名でCIDを意味せず、新config hashがA2Ashleft参照を識別。

v2 train40一致、新旧/A1境界92pass9.62秒、最終全host回帰444pass4skip45.45秒（evaluation/inspect-layout2-host-tests-v1.xml）、compileall成功。全重いテストprocess終了後に実機pilotを行う。source0192ffc2...不変、calf7b80fb3716a13eac239e69fa286d9ddf3464e6ddfd35aa98a5a565be83a946c、detd23fe218af54afc642b04e792ab8cb7d548cadd030c938a9470e60a0866fe6e4、componentsb1922de40076fec02ccdf34d51e15f233b226ac8e8085843a97af61d8976e4cd、固定UTC2026-10-05T18:46:04.017932+00:00。evaluation/normal-inspect-fixed-v2.json。

固定後freshpreflight_v2実機はinput0/E2E0で開始認識通過、normal.993930/margin.192536/hand.994110/empty.995695/detail12950.999391、pointclient375,542召喚円内を独立レビュー。前面/同rect/epoch/hash一致。画像train未使用。同scene時間的再取得で別場面汎化の証明ではない。source/cal/assets固定維持、次pilot結果を優先。

v2登録pilotは2input/1goal失敗interrupted/verification_failed、total3599.910ms、成功0/retry0/fallback0/実2点誤click0レビュー。正常召喚→placement成立後post占有unknown、inspect未実施。内部1461.198ms（認識累計905.281/capture526.216）、verify3270.678/residual1942.127/未分類196.584。認識28回p5031.837/p9537.929ms、1回905msではない。最後runtimeverify画像欠測を明記、停止後別MSSを当時へ代用しない。

停止後read-only診断occupiedRGB.941843/inspect.931586、Main1/center/blank陽性。±4px81位置同最大で位置ずれではない。gray相関.784347（別尺度、emptymax.123019）で単純gray化の表示差解消は未実証。親指定1条件descriptorrows6..24全列除外の同RGBを診断：occupied.980458/inspect.980658、旧positive最小.998293、空負例最大.778586、placement負例最大.789297。有効occupied778/empty330/inspect778、minimum256以上。既知停止後画像で方式選択、holdoutとは呼ばない。別Solarfield表示はunknownで汎用occupancyではない。

Coordinator承認でA2Ash中央field限定のRegion.stable_rgb_excluded_rowsを明示、fixedrows6..24/専用2region/固定component/Ash12950+zone2拘束。旧A1/v1/v2と他featureを維持。v3calとfield-mask-provenance.jsonにmask/proto hashesと有効pixels。新burst訓練無し、RGB.98/.03/min256維持。timeout失敗時だけlast実frame/hash/seq/原clock/state保存、認識未完stateNoneと前last_recognizedを別保存、expectedfacts/prompts/rawscoresは診断のみ、成功hotpath追加同期I/Oなし、failure_diagnostic spanを内部時間へ分類。

v3対象103test成功14.88秒、最終通常環境全回帰455pass4skip51.02秒(evaluation/inspect-mask-host-tests-v1.xml)、compileall成功。固定UTC2026-10-05T19:09:26.721958+00:00/source870c0c2ddadb489603ae21fc8b27bd2ac2b53442e99e2b766c387d382704fc48/c al89c908a67a8e77fa7eb8a21fcd245cec7dfc778b953ba0933a8de312a0aaad37/components e0fa92f14d91465a51deda4785aaf757fd4338b49d00d672cace99f994b20efb、evaluation/normal-inspect-fixed-v3.json。Testerへ現在post固定後MSS10枚input0→offline0認識のみhelper手順を通知。元liveMSS由来/mono/seq/UTC/hashは別保存、履歴無しplannerblocked、同scene時間評価で別場面汎化無し。通過/全回帰終了後に新対戦1pilot、以前失敗trialを成功へ再開/換算禁止。100代表未達、速度最適化未実施。

v4: 新Turn1手札5のpreflightは入力0/pilot0で棄却。旧v1normal参照score.993430とv3.968336、同bbox380/497で探索漏れなし。相対手札v3.978796→(+1,-1).980392。既存2表示参照を同NORMAL位置ごとmax、異位置runner保持するUiEvidenceBankを新profileへ接続。offset27/82、18x112、半径3、score.98/.03/min256、Ash中央限定を維持。新画像訓練0、旧A1/normal/v3asset不変。既知64画像でAsh開始26採用/非menu37不採用、Solar有効normal1はUI陽性だがAsh輪郭不一致、方式選択資料でholdoutではない。

対象116pass＋scope境界1pass。scope fixture初回frozen model直接変更1failはmodel_copyで解消。通常環境full初回268pass4skip201setup errorは全て共通Temp ACL拒否、XML保全。新規workspace basetemp指定full469pass4skip58.08s/pytestcache ACLwarning1(evaluation/inspect-ui-bank-host-tests-v2.xml)。compileall成功、lint/type未導入。今後fullも新規workspace basetemp指定で既知拒否反復を避ける。

microbench20回旧button33.941ms→bank47.344ms、追加13.403ms/hand4.851ms。coverage回復の追加コスト、速度改善・実機E2Eではない。v4固定UTC2026-10-05T19:32:00.570833+00:00/source601210b4d6176248c5b50b978d42ee02a161977fc3a6744f09434d314d89fa54/cal369b9ce8d38fffba9a5dbb2b12541c9185c47f29b078e5c6df1817e807aea9f2/components068ad2473e6d767283134acb3f75130dca466253b46681dbf94f594aa99a14a5/evaluation/normal-inspect-fixed-v4.json。source/assets/helper固定後Testerへ同現scene新MSS10offline0評価→freshpreflight→new1pilot手順通知。100代表未達、既存失敗trialの再開換算無し。

v4固定後新menu10は開始認識3/10、input0/pilot0。Normal10/10/同bbox、hand RGB.987792→.958246。半径3→12で改善無し、時間RGB range平均.128/max.448。静的発光帯の参照追加を棄却。Coordinator承認v5限定で2縦辺＋上辺ANDへ置換、Normal相対ROI/手札帯/幅80..120/重なり65/axis3/maxGap8固定。Hough端点を角と誤って同一視した実画像failを、実Canny edge支持と同一左右線への交差へ修正、交差下65px。パラメータ幅は変更せず、失敗XML全保全。Solar test期待CID9455誤記は実13581へ修正。

v5 handconfidence1はbinary predicate通過で学習確率/CID精度ではない。形状source固定hash、detailCID/Normal種類/empty/現在context/receipt/clock/epoch/blankの独立ANDは維持。RGB rawはconfidence0診断factへ残す。旧v4/A1/normal資産とRGB分岐を保持、新画像訓練0。既知65対比：Ash30候補陽性、placement10/nonselectedpost10/fieldinspect10/opponent3/otherhover1候補0、他CIDnormal1は形状陽性だが13581なのでAsh候補0。field action/Special/Flip/disabled確実資料無し、未検証。方法選択資料でholdout/実機成功とは別。

対象134pass26.64s、hostfull486pass4skip66.63s(evaluation/inspect-hand-geometry-host-tests-v1.xml/session67549完了)、compileall成功、lint/type未導入。microbench20回旧button35.604/bank48.246/手札7.335ms(診断RGB込み)、v4と異画像なので版間改善を主張しない。固定UTC2026-10-05T19:52:22.847196+00:00/sourceea92677c811e34bc17a000a0dcb0b55febac11e024a17deb2e32942e9ffa30fe/calf59a2c018516d809f63e8e30620aece6e177c7736696d5452b33d60625b99672/components2e2713fa0800e78e809f15b7f1116311f2e5876878149d2e020d101eb95aa616/evaluation/normal-inspect-fixed-v5.json。Testerへ同現sceneの新MSS10→freshpreflight→new1pilot通知。source/assets/helper固定維持、100代表未達。


v5固定後の新menu10/10・freshpreflightを経て、登録した実機正常召喚1目的が成功。NORMAL→配置→実zoneinspectの3入力、中央Ashと新詳細CIDを独立レビューしました。E2E2334.8561ms、内部1091.9664ms(capture304.6878/recognition756.5008の反復累計)、verify wall2036.7887/residual1055.7850/未分類187.1047ms。retry/fallback0、3点誤clickレビュー0。residualを純粋なゲーム/通信待機とは呼びません。rawcal SHA f59a...とrun metadata正規化cal3133a977...は異なる定義で、value_hash(parsedcal)の一致をevaluation/normal-inspect-pilot-calibration-integrity-v5.jsonに確認。実機成功1件で100代表/99%達成を主張しません。artifacts/baseline-tester/ASH_INSPECT_PILOT_v5_20261006/tester-review.json。


## Solo意味別応答＋共通book固定（2026-10-06）

Coordinator承認で2semantic応答辞退/strict＋UiPolicy/実Cancel・newseq・陽性outcome/solo_basic_operations subgroup validator/common live epoch guardsを最小追加。summon after10は次Endpromptのみなのでopponent_end_response、modal_absentではない。End after20はselfDraw演出中、idle/ドロー解決/turnnoticeを捏造しない。既知82全分類、未知32candidate0、旧normal40同意味。2Cancel stable20混合は70<256で起動拒否、旧threshold維持・2ROIのみRGB同義max(2048全descriptor画素)へ、全文/phrase/phase独立AND。

初回196pass16failの10はguard snapshot production regression→dynamic propertyで修正、5fixture/1validatorと区別しXML保持。最終対象230pass21.08s、host549pass4skip79.35s(session18469終了/evaluation/response-host-v1.xml)、compileall成功、ruff/mypy/pyright未導入。計装childspanとunion、poll別集計、pureゲーム待機とは称さない。docs/solo-basic-operations.md。

固定evaluation/solo-basic-fixed-v1.json UTC2026-10-05T20:28:11.052070+00:00/sourcef71d56399fac2f40d813ec4426d800f961720c9214c59b4ab64275900236992d/cald1fa9b4aa54a0dced7fca49b69d11b8bc4a05ca383ead7acbc97335e5b96f983/componentsdac03935c08d6203d7cfcb97090496b312e115e4e97bbfeea2c24da39bfc7713。base artifacts/solo-basic-calibration-v2/solo-route.json/ui-rules.json/end-trials.json。source/assets/helpers固定保持、新EndMSS10offline0→freshpreflightinput0→最大1Cancel目的pilotをTesterへ通知し親dispatch済み。新scope実機E2E0、100代表未達。

共通版固定後End10は全文/phrase/phase通過、全面CancelRGBのみunknownで0/10。native1px文字形状へ最小変更（caption78×14・219prototype・R/G160/B100・minrecallprecision.85/new尺度）。confidence1はbinary predicate、disabled実資料未検証。既知新10は方法選択、次holdoutへ流用しない。未知32caption陽性でもsemantic候補0、自然負例/合成反転shiftを分離。

診断出力変数衝突で元訓練Endframe0009をJSON上書き、元画像復元不能。元manifestintegrityfalse/無傷81欠測1を保持、事故報告evaluation/solo-cancel-training-input-incident-v1.json。事故前派生20crop/657固定hash独立監査一致、運用資産無傷。新版builderは固定派生cropから作成、旧82再現を称さず入力81欠測をテスト。出力先新規evaluation/resolve/全入力非重複拒否追加。元path変更/置換なし。

対象223pass38.55s＋最終glyph20pass12.77s、host569pass4skip92.41s(session47101完了/evaluation/cancel-caption-host-v1.xml)、compileall成功、lint/type未導入。固定evaluation/solo-basic-fixed-v2.json UTC2026-10-05T20:53:18.723089+00:00/baseartifacts/solo-basic-calibration-v3/source8a61a55cc99c223d5c36a78980d7ee8b7c043cd181afeca41cf02e94c4471d14/components85150a68aeed81a4c5d31ee25147675d76228f83d59befdf5d1a42b6bf5d3eea/captionconfigfbb8780508c71410efaca2d36ebc64a03d184e1933ea969d29342de8cc6857f4。rawcal/route/UIpolicy旧同値。code/assets/helpers固定後Testerへexactcommand新MSS10→freshpreflight→現End最大1目的pilotを直接通知。新scopeE2E0/速度改善未主張/100代表未達。

Endv2 actualCancel1適正受理だがverifyfailure3477.944ms/成功E2Enull。保存actualseq19/20で自Draw＋DRAW PHASE帯、modal .983859positive/Draw .745709unknown。ROIはTurn数字を除外済、帯coverage不足（数字単独原因を棄却）。最新取得/最新認識PNG+state/hash/mono/seq原証跡保存、停止後Main1へ置換無し。predicate19回536.675ms/p50 27.6285、保存pair再生goal.106ms/全画面changed29.555/expected33.048。typedresponse goalfalse→pendingだけ最小変更、generic/旧normal不変、timeout証跡保持。再生を実機改善量としない。内部union2376.208/verifywall3205.613/residual1013.446/poll1006.973/verify未計測6.473/未分類88.291、失敗artifact186.293含む、puregame推定禁止。

Coordinator承認で旧帯なしDrawOR大DRAW PHASE white形状.90/native1px＋非被覆selfblue割合.15＋modalabsentを接続。knownfailedseq19prototype13903/seq20照合の派生2crop、方法選択/独立成功ではない。実MSS END PHASE2はword .6676/.6734＋bluepositiveでも拒否、実opponentDraw/MAIN/BATTLE/STANDBY未検証。goal newhashsource/freshdiagnostic/wordblue/actualreceipt/newseq境界、旧陽性/idle制限維持。confidence1binary。元訓練81+1欠測保持、診断出力新規evaluation衝突拒否。

typedpending75pass、最終対象175pass29.28s、host592pass4skip100.26s(session93775終了/evaluation/draw-overlay-host-v1.xml)、compileall成功、lint/type未導入。固定evaluation/solo-basic-fixed-v3.json UTC2026-10-05T21:09:07.971420+00:00/baseartifacts/solo-basic-calibration-v4/sourcec2942844c9787913959acbc9a2cb9f0f0367b4e7de07851dcf89a04a49cabba7/components34e04102c3ea8f0738630e8edd9c7831798e04188dfd411a10cd68dd1135cc68/drawconfigb9de9c0c5a9d9d792838996f41747ff1332687712d58b252dc5bdc541dab30eb。rawcal/route/UI同値。code/assets/helpersSTOP→Tester準備済別EndからnewMSS10/freshpreflight/new1pilot exactcommands通知。失敗trial再開換算無し、固定時新版E2E0/100代表未達。

v3Endpilot1Cancel適正受理/elapsed3418.651/E2Enull。actualseq23/24Draw帯＋blue通過word1/.734375/caption0、floor .977614/.978855だけ拒否。床RGB395画素の背景proxyに依存し、LP/hand変動をROI因果に断定しない。内部2139.249/verify3190.081/residual1215.928/poll1208.485/unmeasured7.444/unclassified63.473/predicate5.174、条件違いでE2E改善量主張なし。原verify画像/state保持。

Coordinator承認observed_self_drawをopponentEnd/selfDrawだけ追加。元End＋actualCancel/newseq/client/epoch/fixedhash＋陽性Draw/selfblue、旧全文/Cancel/別knownprompt残留は矛盾拒否。unknownprompt/animation維持、phase/player/activeのみ陽性生成、次入力idle/prompt guard不変。床rawconfidence0診断のみ。default/召喚/normal/phase維持、画像asset/threshold追加変更0。builder初回composite最少条件拒否は書込み前、最少条件緩和せず専用modeへ。比較診断保存後cleanup import漏れexit1をexecution sidecar記録、保存値と成功exitを区別。元訓練81+1保持。

対象178pass18.61s＋最終限定44pass11.15s、host616pass4skip112.94s(session42811終了/evaluation/observed-draw-host-v1.xml)、compileall成功、lint/type未導入。固定evaluation/solo-basic-fixed-v4.json UTC2026-10-05T21:29:18.772976+00:00/baseartifacts/solo-basic-calibration-v5/sourcec3acec46294c7a6856038601a10785fcc41444923d6b0ab32c37f23ebc82a370/components9395f92ef04eb0b62a5e915ab5bae9dbfa1a809a1a3d940183bfce0fb67e3120/route3a179c2189c438e56c8f65a041b7285f8789c5eaa85d72e808f0d055372e9297。cal/画像/UI/Drawcaption config旧同値。unknownprompt目的成功synthetic＋次入力拒否/矛盾/不正hash/旧frame/実input欠測/ledger新mode境界確認。code/assets/helperSTOP→TesternewMSS/preflight/newEnd1pilot exactcommand通知。固定時新版E2E0、100代表未達。

v4End新実機1目的成功E2E2527.866/internal1610.495/capture492.403/recognition1021.406/poll906.303/unmeasured5.170/unclassified5.898/input1retry0、独立レビュー済afterseq18自Draw/元UIなし/unknownpromptanimation維持。実recognition19回p50 54.347/p95 61.344/max74.389。保存2枚メモリwrapper＋bare/topobserver対比でnormal UIbank約91%最大確認（全19画像再現不可）。Controller承認、declaredresponse×activeledger一致verifyだけ銀行探索skip、assetguard/generic/registry/矛盾CaptionDraw保持、freshunknown normalfacts/旧proof不使用、他goal/初回candidate不変。bankchildspan union。

対象v1fixture2fail/172pass保全、savedfreshening/clone相対registryを条件変更無しで正し、v2 174pass17.25s。保存20pair default/scoped応答signature全一致、cold57.907→5.838/61.962→6.321ms、warm56.942→3.860/61.522→4.090ms、guard .93..1.07ms。再生差52..57ms/回で実E2E改善未主張。host631pass4skip117.14s(session3719終了/evaluation/response-verify-scope-host-v1.xml)、compileall成功、lint/type未導入。

固定evaluation/solo-basic-fixed-v5.json UTC2026-10-05T22:02:34.651953+00:00/base同artifacts/solo-basic-calibration-v5/sourcef06abffb87445d4b5799e582e5839d1ea16839baf994e172810589b9397c4cf9/components1013228c37db2428c8d68ef6e88ef2890b1c92ea2093c5367f9e6316505a494f。cal/route/UI/画像asset同hash、元81+1欠測保持。code/assets/helpersSTOP→TesternewMSS/preflight/newEnd1pilot exactcommands通知。新性能版E2E0、100代表未達。雷電機能コードはpilot結果前に編集せず、取得済新資料のreadonly設計のみ進める。

v5固定後新End実機1目的成功run9fd57910c8f5479097317f4106ebb92b、Tester/root独立確認。E2E2614.9034/internal988.3830/capture667.7484/recognition235.7770/poll1609.6701/unmeasured11.2151/unclassified5.6352/input1retry0。bank初回full1/verify skipped32、childunion70.4443ms（親に単純加算しない）。前v4内部-622.1118/E2E+87.0374、条件/観測回数別なので因果改善主張なし。100代表未達。source/assets/helper不変。

次雷電手札①はACTIVATE→専用自分雷電chainCANCEL→autoadd/freshHAND_INSPECTの独立LogicalHandSearchConfirmationを提案、旧strict dark_hand unused/deckavailable unknownは維持し公開UI合法modeを別定義。MSS60stageは訓練/補助E2E0、Sky005に全公開reveal13906→hand格納が見えるが連続NativeMSS欠測。Controller承認で追加Native公開incoming CID→new handslot→blank後実inspectを1回収集、全初期手札CID復元を必須にしない。usedmark/count復帰だけ成功不可、Gy7補助input全てをruntime必須にしない。型/ledger/receipt再利用設計readonly、native素材成立後に実装開始指示を待つ。

## 雷電hand-search段階修正/統合テスト（作業中・実機未実行）

原Native129枚/公開anchor→移動→handoffの資料を採用。source/ready/selected全手札RGBは診断のみとし、sourceは有効effect＋詳細CID＋局所接続矩形、収納readyは実handoffに沿う可視上辺/左辺と安全点、selectedは同X帯の上がった接続矩形へ分離。handoff6の連続資料は欠測なのでready6テストbboxはsynthetic局所診断で実追跡成功ではない。旧source3scene/selected7維持。実edge strip延長が背景横線へ接続する誤採用を除き、selected/sourceでは実Hough線分のみ使用。readyのみfan辺8px＋接続8pxの局所帯を使用し隠れた辺を補完せずsafe interiorを返す。Perception proofはそのbbox/pointを使用、座標validatorは同値・同frame/mono/seqを要求。

初回hand-search再現15件9pass6failXML保全。handoff後もseq/epoch/期限を再検査し、300ms境界の1ns数値誤差のみ許容（追跡品質閾値不変）。時間限定9pass、selected/source限定5pass。ready初回18件17pass1fail保全→局所帯修正18pass→安全点接続込み22pass4.94s（evaluation/hand-search-shape-ready-v3.xml）。原画像/原時計変更0/UI入力0。

新receipt統合16件は初回8pass8fail（evaluation/hand-search-join-v1.xml）で同spec別目的・第三ready欠測・safe point/handoff変更・旧before詳細/blank欠測・隣slot/形状欠測の漏れを検出。begin_stepが前episodeをsnapshotし、goal側の同logical目的/前ready/既存陽性detail_blank/旧詳細未知/実point↔snapshot可視bbox↔handoff↔現在選択矩形をANDへ追加。blankはCIDunknownから生成しない。既存blank認識の資料再生値はready6 .989108、handoff7 .993515。最終shape22＋receipt16=38pass5.22s exit0（evaluation/hand-search-join-v2.xml）、変更6ファイルcompileall exit0。全host/新版固定/実機pilotは次工程、lint/type未導入。観測位相依存のtracker取り逃しは残存し、速度/実機成功主張なし。

hand単独constructor/live epoch guard・事前trial型保持・共通evaluate/preflightのhand開始を接続。runner初回4failは3件Action.confidence欠測と1件synthetic時計1秒の鮮度棄却、原保存時計/production条件は変えずfixtureを補正して5pass。存在しないtest指定で初回target0件exit1もXML保持。CLI --verify-seconds既定3を維持、hand診断だけ8秒/最大20秒/3input/retry0/同操作1へ。107pass/14.48s後host676pass4skip111.56s保全。

局所形状からready/selectedのanimation=False生成を撤去。既存known_main1_clearのself_main1は両ready6/7でunknown（clear_center .98887/.98813、clear_card_menu .98477/.98478だけ陽性）なので、その床/盤面ref追加は行わず第三SELECT_CARD専用の実receipt/handoff/safe proof/blank/fresh ready・自分Main1でunknownを保持して許可。True/別Action/source/prompt/古proof拒否、source/CANCELと旧型は不変。hand3child一意UiPolicyを起動時に必須化。対象147pass15.93s、最終接続64pass17.21s、host695pass4skip120.53sを保全。hand7 inspect_context.main1もunknownの資料はcontext未支持として停止する。

永久trackingfailed初回で実frame/state/原seq/mono/hash/reasonとepisodeを保存し終了、直前実認識frameはbefore_hand_failureの別role。成功経路I/O追加0、再試行0、8秒timeoutとは記録しない。初回1failはsynthetic100×200の縦横比を既存calが拒否したfixture不備→native1280×720へ、87pass16.53s。最終通常ユーザーhost697pass4skip109.21s（session16858終了/evaluation/hand-search-host-first-failure-v1.xml）、compileall src/scripts/tests exit0、ruff/mypy/pyright未導入確認。

新固定evaluation/hand-search-fixed-v1.json UTC2026-10-06T00:56:20.097727Z、819 files。base artifacts/dragondark-hand-search-calibration-v3/source292c4502cd5afbcb38a0a62437bafdd19be9307695f835e0cfec14fe2566c66c/components144fb41ae6ef18aef86585a651fb7073cfd5ae3ff601e378cdfd0d075737b579/rawcal21cb96f51c4d159e6f2f55e5ae306fc0d42b86af0cdc8eeb2775130b7426be9b/route935cb1133d7fe1e068f54d6181a940b6b0b89571cd50cbe8b891a41c170bada3/limits715f20c2c8795dd20e5e2b2be4b14c67d780e0dbdcd9e0fdd2e552c19456a5b2/profile4461e76ea0d62a421e473460cfcb7a35e4a1824479bbb8ee3574bac1b793eb33。source/assets/helpers停止、Tester/rootへ現在hand6slot3から固定後新MSS10→fresh preflight→新1目的pilot exactcommands通知。新scope実機E2E0/100代表未達、旧fixedv5/trial成功への換算なし。

## 固定後detail色変動の小単位修正（2026-10-06・作業中）

新MSS10の開始認識0/10、input/preflight/pilot0。実差分で位置±3px改善なし、header/art/textに非一様色変動。effect10/10だが旧detailRGB .964155..973004、geometry9/10unknown（frame5のみ陽性）の独立不足。全手札RGBは診断値で失敗根拠ではない。full-thumbnail SIFTは共通枠/印刷部の対応で別CID46/46を誤許可して不採用、単純square Canny stripも背景線/未選択へ誤支持して不採用。diagnostic保存初回は旧manifest capture_sequence欠測KeyError/exit1・書込み0、原metadataを保持したoffline seq0で再実行。evaluation/dragondark-source-detail-diagnostic-v1.jsonに全raw/対応点/失敗を保全。

detail単位を先行。native103×150 thumbnail内[12,30,78,72]のartだけへSIFT支持を限定し、descriptor半径5.31×sizeが参照/candidate双方art内に入るkeypointのみ使用。forward Lowe .75＋reverse nearest相互一致（reverse ratioは使わない）、affine RANSAC2px、inliers6/ratio.7/scale.9..1.1/shift3px/spread39×36を固定。新10/10・既知同CID19/20・別CID46拒否。旧known6 frame0004はRGB .944776/.876872とart spread両方不足、OR19/20のunknownを保持し閾値/refで合わせない。少feature/None/common枠only/blankは拒否。

新明示mode rgb_or_native_art_sift_v1だけに旧RGB .98 OR artを接続し、参照特徴を初期化cache。原v3profileはRGB専用で不変、新builderにmode/条件/参照hashを保存。再現19fail39.79s→実装27pass1fail40.78s（bottom境界float差約4e-15px）→数値許容1e-12px明示、越境1e-6拒否のまま54pass47.67s/exit0（evaluation/detail-art-impl-v2.xml）。必要3file compileall exit0、レビュー重大欠陥未確認。geometry/host/freeze/実機は次工程。

同保存10画像・200回/枝・順序反転のHandSearchVision.recognize全体localmicrobench: legacy RGB mean8.7818/p508.5291/p9510.5959/max12.9526ms、新OR mean13.3232/p5013.2328/p9515.1941/max16.8839ms、追加4.5415ms。参照cache後のstat/scene診断/detail/shape込みでcapture/decode/input/E2E外。evaluation/detail-art-runtime-microbench-v1.jsonとbenchmark専用evaluation/profileを新規保存、入力非重複/原hash確認。detail新10は方法選択資料へ転じたためholdout成功とは称さず、geometry未修正なのでsource全体回復も未主張。

## 選択hand内の実art所属（hand v2/profile v4）

左detailの固有artと選択handの実artを対応させるsource-only新modeを追加。参照/candidate双方descriptor全支持はart内、affine/inliers6/ratio.7/spread39×36/scale.9..1.1/回転3°、Effectからart上端58..74px/center差20px。一位置は3pxで同義ref統合。negative-only ambiguity probeはcandidate→ref Loweで弱い同名の対応を保持、各ref最大2モデル/計4反復。primaryだけが陽性根拠、probeは異位置矛盾拒否だけ。同数2clusterはratio不足でunknown、strong60+weak14の単独各陽性モデルは異位置でunknownを確認（synthetic対応点でpixel精度とは別）。条件v1/v2・全資料108・旧unknown理由・synthetic記録を新規evaluationへ保存。

new10 pose10/10、旧source6 pose8/10/旧source7 10/10、selected7所属10/10でもEffect無しでaction0、未選択同Dark10拒否、Ash3/G20/Solar20拒否、新実13908/15011各5拒否・復帰13906×5陽性。旧source6 frame4/5は新pose spread不足、旧Houghもnull/RGB .944776/.901491でunknown維持。新15はResearcher独立detail評価と同じ画像なので件数重複合算しない。全資料は方式選択で独立holdout/E2Eではない。

source_art_pose別keyへ実art bbox/モデル/refhash/同frameを保持、旧source_geometryは新modeでnull＋not_run明示、fullcard枠を捏造しない。現在detail13906+enabledEffect未確認ならnot_applicable/acceptedNoneで重処理を短絡、古pose cache利用無し。GY/現在Main1/同時刻/nativeproof/epochは維持。再現15fail→実装15pass、境界3failの1はambiguousTrue acceptedTrue漏れ→独立not ambiguousを追加、他2はclone registry fixture不足を元校正＋new hand configで修正。115pass1failは負時刻stale fixtureの型制約→synthetic1→2へ補正し当該1pass。sourceモード/params、probe-only、2layout、GY/Main1unknown/staleMain1/no Hough fallbackを閉じ、レビュー重大欠陥未確認。ready/selected endpoint/receiptは不変更。

通常ユーザーfull748pass4skip200.66s（session18405終了/evaluation/hand-art-host-v2.xml）、compileall src/scripts/tests exit0、lint/type未導入。microbenchv1完了回収前にfull開始したため負荷独立性未証明をsidecarに記録し参考値保全。full終了後単独v2: source旧8.0074→新17.0807ms(各200回)、verify旧8.2513→新5.5164ms(各160回)、順序反転/cache後・取得/decode/入力/E2E外。source-art-runtime-microbench-v2.json。保存new10の校正perception/strict/UiPolicyは10/10成立、実機成功ではない。

新固定evaluation/hand-search-fixed-v2.json UTC2026-10-06T02:28:53.016844Z、821files。base artifacts/dragondark-hand-search-calibration-v4、sourcee6260451be5aa37c539de0c38788cc5ce519c9d414e25c73d782112bf6e869ad/componentsa6b750415732a3b9daebac49b01d31907f2a1a725121815183b155e4ab4d71fa/profilea5997715ebcfe556607238b8a4b6f00ad3c9bfc29ba94fb508e8aadf7c5b865e。rawcal/route/limitsはv1同値。原v3/全元画像/旧fixed保持、source/assets/helpers停止→Tester/rootへ固定後newMSS10/preflight/新1目的pilot exactcommands通知。新scope実機E2E0、100代表未達。

## 実親ACTIVATEに結合した自己chain Cancel（作業版・2026-10-06）

v2実機はACTIVATE1回だけ送信、自己chainの全文は陽性だがinspect_context.main1 raw .958639が既存.98未達で第2候補なし、93abstain/time_limit。20.201秒の失敗は保持しE2E成功へ換算しない。診断はevaluation/dragondark-pilot-v2-chain-diagnostic-v1.json（コード変更前）。step1 verify5526.059msは内部4505.683/poll1006.002/未分類14.374で純ゲーム待ちではない。recognition20回2104.551msのうちnormal bank1752.735msは親子spanのため加算しない。性能scopeは別工程。

新宣言own_chain_mode=parent_activation_uiのみ、現在の正確な自己雷電chain全文＋有効Cancel captionを、同logical目的/spec/profile/client/epochの実親ACTIVATE receiptへ結合。現在phase/player/animation unknownは維持し、旧Main1/idle分岐へのfallbackを禁止。既知True/相手/Drawおよびconflicting_positive_evidenceのNoneはstrict側で拒否。入力直前とgoal確認でも現在caption hash/点/観測時刻と実親receiptを再検査。旧current_main1 mode/通常/相手応答は維持、caption confidence1はpredicate通過で確率ではない。

time_limit終了は最後の実runtime frame/stateをrun_endpoint、最後の実認識が別frameならrun_last_recognizedとして既存failure保存経路に保全。新capture/保存画像fresh化/成功hotpath PNG追加なし。原中間afterseq20は元trial最終画面の欠測を埋めない。

再現v1は新purpose引数未実装16fail/10pass。v2はfrozen Rule fixture26setup error/1pass、v3はfrozen Frame5・planner参照fixture1・uint8 fixture1の7fail/26passを保全。fixtureはmodel_copy/dataclasses.replaceで原画像・原clockを変更せず修正。boundary-v4は33pass54.63s、入力直前/goal結合と旧型関連はown-chain-related-v1.xml 206pass99.61s/exit0、全Pipeline追加1pass2.23s（own-chain-pipeline-v1.xml）。compileall src/scripts/tests exit0、ruff/mypy/pyright未導入。実失敗contextをnew spec/activeへdeepcopyした試験はsynthetic fixtureであり原trial救済ではない。raw interrupted contextは拒否する負例を保持。

新anchor対応の独立診断を待つため、この単位で全host/freeze/実機は未実施。旧v4資産/全原画像/旧固定は保持、GUI入力0。Coordinator所有baseline-research文書は編集しない。
