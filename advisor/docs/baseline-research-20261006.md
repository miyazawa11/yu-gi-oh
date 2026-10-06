# 初回調査と実機baseline（2026-10-06）

## 評価範囲と現在の判定

ユーザー指定の現在のデッキ・ソロモードで計測。初回はResearcherがコードを変更せず調査し、その後に未変更版の実機baselineを取得した。

**100件の代表Actionによる目標は未達。** 下記は異なるソース版で各1件のフェイズ移行を完了した限定計測であり、合算して本試験の件数・精度・改善量を主張しない。通常召喚の訓練・認識検証、画面準備の補助操作、OCR実験は自律E2Eの件数に含めない。

役割の実セッション設定は、CoordinatorがGPT-6 Astra / Medium、ResearcherがGPT-6.1 Sol / Low、ImplementerとReal Device TesterがGPT-6.1 Sol / Medium。難しい状態遷移の実装はHigh担当へ切り替え、編集者は同時に一人とする。

## 初回調査の10項目

| 項目 | 確認した構成・限界 |
|---|---|
| ディレクトリ | `src/master_duel_advisor`が本体。`tests`、`scripts`、`data`、`config`、`docs`、`evaluation`、`artifacts`、`benchmarks`がある。既存構成を維持。 |
| 画像取得 | `capture.py`のMSS / dxcam。現agent-loopはMSS。取得開始・終了の性能時計と、画像の鮮度用monotonic時刻を区別する。 |
| 画像認識 | `perception.py`のROIごとのRGB / stable_rgbテンプレート照合と差分キャッシュ。数値は必要時にTesseract。毎フレームの全画面OCR・LLM呼出は基本経路にない。 |
| ゲーム状態 | `models.py`のGameStateに盤面、phase、prompt、card/factと認識確度・出典・時刻を保持。未知ゾーンを空として扱わない。 |
| 行動決定 | `pipeline.py`で候補生成、strictルール、planner、DecisionEngineを実行。既定順位は認識確度等であり、汎用的な勝率最適化の完成を意味しない。 |
| UI操作 | `agent_loop.py`の校正座標解決と`safety.py`の前面・矩形・被覆・範囲・鮮度検査。送信しただけでは成功にしない。 |
| テスト | pytest単体・模擬統合、合成demo、校正監査、実画像評価。初回保存結果は304成功/4skip。後続変更の結果は各実験文書とXMLに分けて保存。 |
| 実機操作 | 事前登録trialを使うagent-loop。入力前後画像と目的単位ログを保存し、Testerが独立レビュー。Computer Useによる準備は補助として除外。 |
| 各処理の時間 | 下表の実機計測を参照。過去の画像取得・認識だけのベンチマークはE2Eに置き換えない。 |
| 3秒達成への障害 | 現時点の主な不足は操作・盤面の認識範囲。単一例では結果確認wallが最大、内部計測ではcaptureが最大。代表100件における最大ボトルネックは未確定。 |

## 目的単位の実機計測

目的はいずれも「Main1からEndへ移行」。開始画像取得からEND PHASE / Turn2 Endの画面確認までを1目的とし、子入力は2件。

| 指標 | 初回の未変更baseline | 計測整合性修正後の回帰baseline |
|---|---:|---:|
| ソースSHA256先頭 | `0f6ef470` | `d7c39a50` |
| 目的数 | 1 | 1 |
| 平均 / p50 / p90 / p95 / 最大（ms） | 各623.411 | 各579.065 |
| 成功 | 1/1 | 1/1 |
| 誤クリック（独立レビュー） | 0/2 | 0/2 |
| 再試行 / Fallback | 0 / 0 | 0 / 0 |
| 計測済み内部span合計（ms） | 157.619 | 120.846 |
| capture合計（ms） | 117.078 | 92.195 |
| recognition合計（ms） | 16.502 | 14.234 |
| state build合計（ms） | 0.797 | 0.827 |
| candidate / decision合計（ms） | 0.096 / 0.144 | 0.085 / 0.146 |
| coordinate / input合計（ms） | 0.022 / 22.978 | 0.022 / 13.336 |
| 確認wall合計（ms） | 474.261 | 448.043 |
| 確認中の待機推定残差（ms） | 365.995 | 358.780 |
| 未分類（ms） | 99.797 | 99.439 |

確認wallは内部の取得・認識spanと重なるため、各段階を単純加算しない。待機推定残差にはpoll待ち・未計測Python処理も含まれ、純粋な演出時間やサーバー通信時間の直接測定ではない。内部spanも全処理を網羅しておらず、未分類時間を明示した。意味的な判断誤り全体の監査は、誤クリックレビューとは別の残課題。

両版は少数かつ異なる実機状態での計測。差をコード変更による短縮量と断定できない。

保存済みspanの追加解析では、未分類時間のうち初回97.347ms・回帰97.041msが、2回のcoordinate終了→input開始（各29〜35ms）と1回のverify終了→次state_build開始（約32〜34ms）に位置した。両runのsettle_secondsは0。該当コードにはPNG保存・ログ・制御処理が含まれるが、個別spanがないためPNGだけへ帰属しない。verify内の50ms周期poll待ちはこの未分類時間とは別であり、次の計装ではartifact/log/control/poll待ちを分ける必要がある。

証跡：

- `evaluation/baseline-tester/baseline-20261006T0120/`：初回レポート、固定ソースZIP、入力レビュー、画像、ログ。
- `evaluation/baseline-tester/phase-regression-d7c39-20261006/`：新版のレポート、入力レビュー、集計。

## 計測と認識で発見・修正した事項

- 版・cohort・校正・試行予定が違うログを合算して合格できないよう、事前固定manifestと整合性検査を追加。本試験はofflineカード知識を必須にし、DB変更を検出する。旧pilotの参考統計は保持する。
- 保存画像を約5秒後に処理し、perf_counter値を鮮度時刻として渡した事前評価は誤りだった。元ログを残し測定手順エラーと訂正。pipelineを先に初期化し、LiveCaptureSourceの新規monotonic観測で評価すると3/3適合した。安全条件を緩めていない。
- 小さな手札画像からの人間のカード名誤読を、詳細表示とローカルDBで訂正。旧記載・根拠・訂正履歴を保持し、誤ったカードIDを学習へ流用していない。
- 太陽電池メンpost校正v1は訓練に一致したが、固定後の新画像0/3で失敗。局所的な色変化を測定し、閾値を下げず安定表示用v2を作成。新post3/3、既知負例88/88を確認。別対戦の通常召喚E2E成功の証明ではない。
- 日本語名OCRは小ROIだけで評価。固定評価の全文一致26/33、信頼度ゲート後採用8/33、誤CID0、平均176.448ms。通常判断へは統合していない。
- 選択詳細名の小さなCIDレジストリを追加。登録はG・Solar・Ashの3種に限定し、score 0.98とtop1/top2差0.03を要求する。固定後の新画像12枚（Ash3、未登録Driver3、未登録Dark3、名前なし3）は12/12一致・誤CID0、認識だけの平均0.305ms。所属zoneや操作を推定せず、Action/GameStateには未接続。追加moduleを含むソース`ac8d0752`での自律E2Eは未計測。

関連する実装・実験の条件と限界は、`benchmark-baseline.md`、`solar-normal-profile.md`、`card-name-ocr-experiment.md`、`detail-name-registry.md`を参照。

## 通常召喚ボタンの局所探索（未接続）

G/Solarの既存テンプレートを有限範囲で探索する部品を追加し、設定SHA256 `38ac24d4a30f0606a8d46cd4c1dfcf16c1289cf6528f8c5e844a434867f38e1f`、検出module SHA256 `8c818d99c8b3da29d9b2b34e78b42234b58d6fe4d7cc91ce7f7907beb2570032`で固定。固定後に灰流うららの新MSS画像3枚を取得し、別担当が予測を見ずに通常召喚陽性を確認した。検出は3/3、score最小0.996274、margin最小0.237895。局所探索だけの平均33.087ms、p95 34.311msで、画像取得・入力・結果確認を含まない。

切抜きbbox原点を独立に3px精度で確定できていないため、bbox合格はnull、位置を含む総合判定は未達とした。特殊召喚・反転召喚・無効召喚との識別も未検証。CIDや所属ゾーンは返さず、入力には未接続。新規補助操作・資料取得を自律E2Eや100件の一部として数えない。結果は`evaluation/action-evidence-ash-holdout-v1.json`、原資料は`artifacts/baseline-tester/ACTION_EVIDENCE_ASH_FIXED_v1_20261006_retry/`に保存。

## 残る完了条件

通常召喚の新しい結果確認用に、同一MSS取得元でmenu/placement/post-unselected/post-inspectedの各10枚を補助収集した。補助入力5回（詳細閉じ・手札再選択・召喚・配置・実フィールド選択）、通常召喚1回であり、自律E2Eは0件。中央配置後は詳細欄がなく、中央の実カードを選択した後に灰流うららの詳細が表示された。一方、独立した選択ハイライトは確認できておらず、存在するものとして扱わない。資料は`artifacts/baseline-tester/ASH_NORMAL_INSPECT_TRAIN_v1_20261006/`。

同収集の連続104枚は、配置入力より前に撮影が終了した計測手順の失敗だった。元資料を保全し、配置待ち画面の診断用途に限定。召喚後の成功画像・演出時間・ゲーム待機時間へ転用しない。

新しいinspect確認ルートv1は訓練40/40、固定版の通常ユーザー環境テスト440成功・4skipを確認した。しかし別対戦（Turn2・手札6）の新MSS事前確認は開始条件不足で停止した。ソース`0192ffc2ac4d7d787a5ad6eb04412a7774d21fe73cc68918383ed3103afd9e76`で、召喚ボタン最大score 0.976373、中央empty 0.978574が0.98に届かず、手札選択輪郭も0.854690だった。局所探索の追加精査でも最大値は変わらず、探索漏れではなく表示条件の支持不足と分類した。詳細CIDとMain1、foreground/rect/入力epochは確認できたが、入力0・E2E0のまま。証跡は`artifacts/baseline-tester/ASH_INSPECT_PREFLIGHT_v1_20261006/`、診断は`evaluation/normal-inspect-preflight-diagnostic-v1.json`。失敗画像を訓練へ流用せず、別途新しい訓練資料によるv2を進める。v2の改善・実機成功はまだ未確認。

代表操作の認識・合法候補・結果確認範囲を増やし、同一の事前固定試験条件で100目的以上を実機計測する。平均3000ms以下、p50 2500ms以下、p95 5000ms以下、成功率99%以上、誤クリック率0.5%以下を同時に確認する。失敗・再試行・Fallbackを分母やログから除かず、未分類時間と意味的誤操作の監査も残課題として扱う。

## inspect確認ルートv2の実機失敗（2026-10-06）

v2の新MSS事前確認は成功したが、登録した自律pilot 1目的は結果確認で失敗した。召喚と中央配置の2入力は目視で正しく、最後のinspectは未実行。成功0/1、子入力の独立誤クリックレビュー0/2、再試行0、fallback0。CLI終了コード0を目的成功の証拠にせず、logical resultの失敗を保持した。試行経過3599.910ms、成功E2Eはnull。内部span合計1461.198ms（capture526.216、recognition905.281、state3.642、candidate0.157、decision0.265、coordinate0.056、input25.581）、verify wall3270.678ms、確認残差1942.127ms、未分類196.584ms。recognitionは確認待ち中の反復累計であり、1回の認識時間ではない。純ゲーム待機時間の直接測定ではない。

停止後の別MSSではoccupied score0.941843・inspect候補0.931586に対し、明示blank0.992559等は陽性だった。±4px探索でも改善せず、同カードの表示条件に対するRGB特徴の弱さが候補。ただし最後のruntime取得画像が欠測しており、停止後画像を当時の最終画像へ置き換えない。次修正ではtimeout時の最終frame/stateと期待条件の保存を追加し、既知画像による特徴比較から認識方針を決める。証跡は`artifacts/baseline-tester/ASH_INSPECT_PILOT_v2_20261006/`。

続く既知画像の診断では、平均除去・L2正規化grayも旧occupied最小0.993602から停止後画像0.784347へ低下し、単純灰色化で表示差を解消できなかった。別の固定条件としてdescriptor rows6..24を除外すると、同じ停止後画像のoccupiedは0.980458、inspect候補は0.980658になった。有効画素は両者778で最低256を維持し、旧occupied20枚の最小は0.998293、empty10枚の最大は0.778586、placement10枚の最大は0.789297だった。この画像は方式選択に使った既知資料であり、独立評価や実機成功とはしない。cursor/hoverが原因とも断定しない。

このmaskはAsh専用inspect確認profileへ限定して接続し、旧A1・通常召喚profileや汎用occupied判定へ広げない方針とした。既存score0.98・margin0.03を維持して条件とソースを固定した後、まず新MSS画像で入力なしの認識評価を行う。旧試行の失敗は保持し、その後の別対戦を新しいpilotとして測定する。診断資料は`evaluation/normal-inspect-central-mask-diagnostic-v2.json`と`evaluation/normal-inspect-central-mask-contrasts-v2.json`。

v3をソース`870c0c2ddadb489603ae21fc8b27bd2ac2b53442e99e2b766c387d382704fc48`、校正`89c908a67a8e77fa7eb8a21fcd245cec7dfc778b953ba0933a8de312a0aaad37`で固定し、全回帰455成功・4skip、compileall成功を確認した。ruff/mypy/pyrightは未導入でlint/typecheckは未実行。固定後に現在のpost状態から新MSS10枚を取得すると、期待認識は10/10一致した（occupied最小0.980459、明示blank最小0.989980）。独立目視も中央Ash・詳細欄なし・自分Main1と整合した。同一場面の時間的な新画像による評価であり、異なる対戦への汎化やE2E成功ではない。入力0、履歴なしplannerは10/10 blockedのまま。資料は`artifacts/baseline-tester/ASH_INSPECT_POST_TEMPORAL_v3_20261006/`と`evaluation/ash-post-temporal-v3.json`。

前回v2のspan解析ではcapture/recognition各28回、recognitionのp50は31.837ms・p95は37.929msだった。失敗した2回目verify内だけで24回の認識があり、capture開始間隔は121.162〜135.605ms。50msのpoll待ちに取得・認識・未分類制御が加わった実周期である。認識終了から次captureまでは73.340〜78.016msであり、純ゲーム待機へ帰属しない。まず結果認識の正確性を直し、その後必要な個別spanを追加して待機・制御・predicateの内訳を測る。

別対戦の準備を3回行い、1・2回目は対象カード不在、3回目は先攻Turn1 Main1・手札5枚の左端Ashを選択した。v3のfresh preflightは不適合で入力0・pilot0だった。詳細CID0.999036、Main1 0.998417、clear_center 0.999314、中央empty 0.996720は一致したが、hand_selectedとsummon_enabledがunknownになった。前回の手札6枚からの表示差を候補として局所探索範囲と選択根拠を調べる段階で、原因は未確定。補助12入力はKPI対象外。資料は`artifacts/baseline-tester/ASH_PILOT_V3_PREPARATION_20261006/`と`artifacts/baseline-tester/ASH_INSPECT_PREFLIGHT_v3_20261006/`。開始前不適合を実行済み目的の成功・失敗へ混ぜない。

この開始画像の局所診断では、召喚ボタン最大位置は旧・新版とも`[380,497,74,79]`で、探索範囲漏れではなかった。v3参照のscoreは0.968336だが、未変更の旧v1参照では0.993430となり、参照置換による表示coverage不足を確認した。手札輪郭は相対位置の固定照合0.978796、1pxずれの照合0.980392だった。既存の同意味参照を位置ごとに統合し、手札の相対位置を半径3pxまで探索する候補を既知64画像で比較すると、Ash開始26枚は26/26、非menu37枚のボタン採用は0/37。別カードSolarの有効normal1枚ではボタンを検出するが、Ash手札輪郭とCID条件には合わなかった。これは方式選択用の既知画像比較で、未見holdoutではない。閾値を維持したv4を実装し、新画像と新pilotで確かめる。資料は`evaluation/normal-inspect-hand5-diagnostic-v3.json`と`evaluation/normal-inspect-prototype-bank-diagnostic-v3.json`。

v4はソース`601210b4d6176248c5b50b978d42ee02a161977fc3a6744f09434d314d89fa54`、校正`369b9ce8d38fffba9a5dbb2b12541c9185c47f29b078e5c6df1817e807aea9f2`で固定。全回帰469成功・4skip、compileall成功。初回全回帰の201 setup errorは共通TempのACL拒否と特定し、失敗XMLを保存したうえでworkspace内の新規basetempで解消した。20回の部品計測は旧button平均33.941msに対しbank47.344ms、手札照合4.851msであり、高速化ではなくcoverage回復の追加コストである。

しかし固定後の新MSS10枚では期待factsの一致は3/10に留まった。召喚ボタン10/10（score0.99434〜0.99578）、Main1・empty・CIDは通過したが、手札選択は最初の3枚だけ通過し、残り7枚はunknown。目視では同じAsh menuを維持していた。入力0・fresh preflight0・pilot0で停止し、輪郭の時間変動と特徴設計を再調査する。資料は`evaluation/ash-menu-temporal-v4.json`と`artifacts/baseline-tester/ASH_INSPECT_MENU_TEMPORAL_v4_20261006/menu/manifest.json`。固定後データを都合のよい3枚だけに限定して合格扱いしない。

時系列診断ではボタンbboxは10枚とも`[380,497,74,79]`で固定。手札の最良scoreは0.987792から0.958246へ低下し、不適合7枚は探索半径を3から12pxへ広げても最良score・位置が改善しなかった。18×112の局所特徴のRGB rangeは平均0.1280・最大0.4484（0〜1尺度）で、位置探索の不足より時間的な表示変動が支配的だった。静的RGB輪郭の参照追加を反復する方針は棄却し、せり上がったカードの辺・隣接手札との相対高さを独立した形状証拠として検証する。詳細CIDや他の安全条件を形状だけで代用しない。資料は`evaluation/normal-inspect-hand-temporal-diagnostic-v4.json`。

形状の単一条件による方式選択比較では、Canny 50/150とHoughP（rho1、theta1度、threshold40、minLength65、maxGap8）をボタン相対ROIへ適用し、ほぼ垂直の左右2辺・幅80〜120px・重なり65px以上・所定位置の上辺を要求した。既知の時間変動10枚と旧menu各10枚の計30枚で陽性、post非選択/field inspect計20枚で陰性だった。これは既知資料の診断であり未見評価ではない。v5実装ではさらに上辺両端と左右辺の接続を8px以内（線抽出のmaxGapと同じ）に制限し、同一矩形を要求する。相手turnにも選択手札外形と詳細が存在する資料を確認したため、形状だけを合法性へ転用せず、Normal button・詳細CID・Main1等とのANDを維持する。special/flip/無効normalの確実な実機対比資料は不足したまま。資料は`evaluation/normal-inspect-hand-geometry-diagnostic-v4.json`。

## inspect確認ルートv5の実機成功1件

Hough線分端点を角とみなす初期接続実装は発光時に本物のカードを拒否した。最終版は元Canny pixelの縦線支持を固定maxGap8・axis許容3で確認し、上辺と左右線の交差位置から下へ65px以上の同一矩形を検査する。失敗XMLを保持し、対象134成功、通常ユーザー全回帰486成功・4skip、compileall成功を確認した。lint/type checkerは未導入。部品20回平均は旧button35.604ms、bank48.246ms、RGB診断と形状を含む手札7.335msで、高速化の主張ではない。

ソース`ea92677c811e34bc17a000a0dcb0b55febac11e024a17deb2e32942e9ffa30fe`、校正raw bytes SHA`f59a2c018516d809f63e8e30620aece6e177c7736696d5452b33d60625b99672`で固定。新MSS開始画像10/10とfresh preflightが通過した後、新しい自律pilotで通常召喚→中央配置→実カードinspectの1目的が成功した。E2E2334.8561ms、入力3、再試行0、fallbackなし、独立レビューで誤クリック0/3。最終実機画面は中央Ash 0/1800と左Ash詳細を確認した。1件の成功であり、100代表目的や分位性能の達成を示さない。

内部span合計1091.9664ms（capture304.6878、recognition756.5008、state1.9960、candidate0.1716、decision0.3088、coordinate0.0650、input28.2364）。verify wall2036.7887msは取得・認識と重複する。確認残差1055.7850ms、未分類187.1047msであり、純ゲーム/通信待機の直接実測ではない。runtimeのmisclick未判定値は保持し、独立目視レビューと分けた。

metadataのcalibration SHA`3133a97712a1f821bf15c29600bed6e21911ee9fb0ab6c8872ea6539994f6ec1`は正規化したCalibrationモデルのvalue_hashで、raw file SHAとは対象が異なる。現ファイルとmetadataモデルから同値を再生成し、source/componentsも固定版一致を確認した。資料は`artifacts/baseline-tester/ASH_INSPECT_PILOT_v5_20261006/`（run `a1eefc7cf458453f864138d5faf68ea4`）、`evaluation/normal-inspect-pilot-calibration-integrity-v5.json`。旧v2失敗・v3/v4開始不適合は別資料として保持する。

## 意味別の任意効果辞退の拡張

相手の召喚成功時とターン終了時を別promptとして、既存UiPolicyとstrict ruleの両方に一致する一意Cancelのみを許可する経路を実装中。発動候補の詳細CIDが見えない場合はunknownを維持し、ソロ試験用の任意発動辞退方針として扱う。戦略的な最善手の主張ではない。実MSS・入力履歴・新sequence・明示的なmodal消失と陽性の遷移先を組み合わせ、単なる画面閉鎖だけで成功にしない。

`artifacts/baseline-tester/OPTIONAL_RESPONSE_TRAIN_v1_20261006/`へ補助収集を開始した。魔法/儀式/モンスター効果へのチェーン確認と攻撃宣言への確認は、上記2promptとは別の負例として保持する。補助Cancelは実機資料収集であり、自律E2Eやruntime送信済み証拠へ換算しない。

終了時beforeは赤Turn2 Endで「相手がターンを終了しようとしています。カードの効果を発動しますか？」。Cancel後のMSS20枚はTesterとResearcherの独立目視で、すべて青Turn3 Draw・中央ドロー演出・modalなしだった。最初の原seq39/mono73501.953を含む資料を保持するが、値自体はruntime条件へ固定しない。MSSではTURN noticeを取り逃し、Sky直後画像だけにTURN CHANGEがあり、取得元・時計の違いを保持する。正式outcomeはself_drawとmodal_absentに限定し、idle・ドロー解決・次入力可能を捏造しない。新scopeの自律成功と性能は未検証。

初回の新応答経路の対象回帰は196成功・16失敗。旧inspect goalを起動後に付ける反例で、guard有効性を起動時のboolへ固定した変更により10件の棄却漏れを検出した。動的propertyへ修正し、fixtureと合成book検査の残り6件も直して対象212成功を確認した。production回帰とfixture不備を分け、`evaluation/response-target-v1.xml`と再実行v2を保持する。

上限内のRetry2で召喚成功時のbefore10枚（原seq62〜71）を取得した。補助Cancel後10枚（seq72〜81）はすべて次の相手End任意応答で、modalなしの赤Main1は取り逃した。afterを通常画面とラベルせず、召喚辞退には別のtyped outcome `opponent_end_response`を追加する。これは実Cancel・新sequence・元summon promptの消失・別のEnd全文/赤Endへの移行を確認するもので、modal_absentを捏造しない。素材不足のclearMain1経路を有効化せず、End→selfDrawの条件も維持する。現在のEnd応答画面を保持し、新版固定後に新画像と独立pilotで検証する予定。

補助収集は82/82枚eligible・17入力で終了し、runtime入力/E2Eは0件。最初のCancel校正はhover/非hoverの混合により安定画素70で最低256を満たさず、安全拒否となった。ボタン2領域のみ同義RGB参照の最大一致へ変更し、178×40原画素からdescriptor2048全画素を使用した。閾値0.98・margin0.03と独立したstable全文/phrase/badgeのANDを維持する。既知82枚では召喚before10/10・Endbeforeと次End計20/20・Drawafter20/20が対応状態と一致し、別chain/儀式/効果/攻撃32枚は候補0だった。`evaluation/solo-response-training-diagnostic-v2.json`は訓練資料での比較であり、固定後実機評価ではない。poll/guard/predicate/artifact/logの子spanを追加し、区間unionによる重複除外のテストを進めている。

共通版は対象230成功、全回帰549成功・4skip、compileall成功後に固定した（`evaluation/solo-basic-fixed-v1.json`、source `f71d56399fac2f40d813ec4426d800f961720c9214c59b4ab64275900236992d`）。しかし新End画像10枚では0/10適合だった。End全文・識別phrase・赤Endは高一致だが、cancel_enabledだけunknownとなり、fresh preflight/pilotとも未実施・入力0で停止した。固定版の全hashは評価helperで一致を確認。ボタン色の参照追加を反復せず、差分集中箇所と文字/形状の安定性を診断する。新資料は`evaluation/solo-end-temporal-v1.json`と`artifacts/baseline-tester/SOLO_END_FIXED_TEMPORAL_v1_20261006/end/manifest.json`。テスト成功を実機成功に置き換えない。

## 診断時の元画像上書き事故

Cancel形状診断中、保存先変数を画像ループで再利用する実装ミスにより、`OPTIONAL_RESPONSE_TRAIN_v1_20261006/end-response-before/frame-0009.png`が診断JSONで上書きされた。元SHAは`a9f002de3b0301dd4815ea28febcf893da089a106b90bbb27b214988591efae7`。診断を停止し、元pathはさらに変更せず事故reportを保存した。Highの再hashでは訓練82枚中81枚一致・1枚不一致、新しい固定後10枚および固定source/assets/helpersは一致。現在の元訓練manifest integrityはfalseであり、事故前の82枚評価と現在の再現性を区別する。

同一ハッシュのフル画像コピーを別担当がread-onlyで調査中。crop・別frame・別取得元から原画像を作り直して復元扱いにはしない。今後の診断出力はevaluation配下の新規pathに限定し、resolve後の包含・入力集合との非重複・既存path拒否を保存前に検査する。資料は`evaluation/solo-cancel-training-input-incident-v1.json`。元画像を失った事実を過去結果から消さず、影響を明示したうえで作業を再開する。

独立監査ではプロジェクト内14,159画像と5ZIPに元hashと一致する複製はなく、1枚は復元不能の欠測と確定。固定manifestの657ファイル記載・合成source SHA・rawcalはすべて一致した。診断を無傷81枚・固定後10枚・旧normal40枚・事故前の固定End crop20枚で再開し、入力hashを個別記録した。原82枚manifestの不整合は維持する。

## Cancel文字形状への変更案

新End画像の全面RGB scoreは0.933805〜0.943488、±3px探索で改善なし。文字だけのRGBやstable maskでも改善しなかった。単一の黄色glyph抽出（R/G≧160、B≦100）とnative1pxの対称形状許容では、旧End/次End19枚score1、旧summon/別chainの共通Cancel0.891892、新しい既知10枚0.891892〜0.897727だった。自然負例の効果文字・Draw・normalmenu・placementは0、normalpostは最大約0.0548。合成反転/4pxshift/全面黄色はそれぞれ0.730594/0.6073/0.5101。合成負例を実機精度の証拠へ置き換えない。

新尺度でthreshold0.85を方法選択条件として宣言し、response専用経路へ実装する方針を承認した。RGB閾値0.98を密かに緩めたものとはせず、尺度・ROI・1px許容・色proxy・thresholdをhash固定する。caption ROI `(506,674,78,14)`はbutton `(456,661,178,40)`内、宣言click `(545,681)`との対応を保持する。共通captionが別promptでも陽性なのは想定どおりで、候補許可には意味別全文/phaseの独立ANDが必要。disabled Cancel実資料は不足。confidence1は形状predicate通過で、確率ではない。今回の新10枚は方式選択に使用したため、さらに固定後の新MSSで評価する。資料は`evaluation/solo-cancel-native-shape-diagnostic-v1.json`。

## 終了応答pilotの認識失敗

caption版は対象223成功・最終境界20成功・全回帰569成功4skip・compileall成功後、`evaluation/solo-basic-fixed-v2.json`で固定した。ソース`8a61a55cc99c223d5c36a78980d7ee8b7c043cd181afeca41cf02e94c4471d14`、components `85150a68aeed81a4c5d31ee25147675d76228f83d59befdf5d1a42b6bf5d3eea`、profileは`artifacts/solo-basic-calibration-v3`。

終了応答1pilot（run `bec4e4617d8542459e535c4fd8c93d66`）は入力1・再試行0・fallbackなし、verification_failedで中断した。経過3477.944ms、successful E2Eはnull。独立目視でclient `(545,681)`は適正Cancel位置、入力受理後selfTurn2へ移行。保存されたruntime seq19/20のPNGとsidecarには青DrawとDRAW PHASE overlayがあり、modal_absentは0.983859でtrueだがself_drawはunknownだった。Recognition failureとして記録し、停止後Main1観察を成功endpointへ置き換えない。証跡は`artifacts/baseline-tester/SOLO_END_PILOT_v2_20261006/`。

新計装値は内部2376.208ms、verify wall3205.613ms、poll1006.973ms、従来の確認残差1013.446ms、verify内未計測6.473ms、verify外等の未分類88.291ms。従来残差にはpollが含まれ、単純加算しない。predicate536.675ms、artifact186.293msも記録された。まずself_draw特徴の表示差を診断し、predicateの内訳も実測根拠に従って確認する。これらは純ゲーム/ネット待ちの直接測定ではない。

実画像診断ではselfDraw scoreはseq19で0.7457086、seq20で0.7453644。ROI`[946,320,86,26]`はTurn数字を含まず、DRAW PHASE帯による広域の色変化が主な未対応条件だった。runtime predicate19回は計536.675ms。保存された実before/afterペア20回の再生計測ではgoal_confirmed平均0.106ms、全画面changed29.555ms、Verification.expected33.048ms。predicate内にhash読取りはなく、全画面float差分が主コストというコードと再生結果が整合した。再生値を実機改善量とはしない。

typed responseだけgoalfalse→pendingを直接返す最小修正を行い、generic/旧normal分岐を変えず関連75テスト成功。認識代替の単一比較では、native1px白文字のDRAW PHASE ROI`[416,337,455,51]`と、非被覆selfblue ROI`[970,294,32,18]`を使用。既知runtime2枚はwordscore1・blue割合約0.72、旧Draw20はword最大0.4026・blue約0.71、旧normal40はword最大0.2912。方法選択条件はword≧0.90・blue割合≧0.15・modal_absentのANDとし、既存overlay無しDraw判定とのORで限定接続する。白単色・反転・6pxshiftの比較は合成資料であり、相手Drawや他phase帯の実負例不足は別途明示する。既知失敗2枚を独立holdoutとはしない。資料は`evaluation/solo-end-pilot-readonly-diagnostic-v2.json`、`evaluation/response-pending-target-v1.xml`、`evaluation/solo-draw-overlay-shape-diagnostic-v1.json`。

Draw対応版は対象175成功・全回帰592成功4skip・compileall成功で固定（`evaluation/solo-basic-fixed-v3.json`、source`c2942844c9787913959acbc9a2cb9f0f0367b4e7de07851dcf89a04a49cabba7`）。実MSSのEND PHASE負例2枚はwordscore0.667554/0.673380、selfblue陽性でもDraw条件は拒否した。別のEnd確認へ補助6入力で進み、固定後の新MSS10/10とfresh preflightが通過した。

独立v3pilot（run`5fa53d599ff146f9b88c96180748a682`）は入力1・再試行0・fallback0、経過3418.651msで再びverification_failed、successful E2Eはnull。runtime seq23/24でmodal_absentとself_drawがunknownだった。rootも最終取得PNGで青Turn4Draw・DRAW PHASE帯・元応答なしを目視したが、これを自動成功へ換算しない。盤面は相手モンスター追加・LP5200等が前回と異なり、静的背景に依存したmodal_absentが阻害していないか調査する。

今回内部2139.249ms、verify3190.081ms、poll1208.485ms、従来残差1215.928ms、その内未計測7.444ms、未分類63.473ms。predicateは5.174msに減ったが、異なる実機状態のためE2Eの差を同条件の改善量とはしない。失敗証跡は`artifacts/baseline-tester/SOLO_END_PILOT_v3_20261006/`。

分離診断ではv3失敗画像のDraw wordscore1.0・selfblue0.734375は成立し、元Cancel captionも不成立だった。阻害要因は旧modal_absentの床色prototype一致（seq23 0.977614、seq24 0.978855、閾値0.98）だった。ROI`[425,440,427,42]`は元文言panel位置だが、不在の陽性参照が特定盤面の床模様に依存していた。LP/手札はROI外なのでそれら自体を原因と断定しない。

改善はopponentEnd→selfDraw限定の`observed_self_draw`を追加し、前End・実Cancel・新sequence・同client/epoch・固定sourceの陽性selfDrawへ直接goalを結び付ける。元全文/Cancel/既知promptが残る明示矛盾は拒否する。prompt unknownをnoneへ書き換えず、床色はconfidence0の診断値へ移し、次入力のidle/prompt guardは維持する。従来default goal、召喚応答、normal、phaseは条件を緩めない。旧Draw20枚は陽性20/矛盾0、旧before/未知61枚はDraw陽性0/旧UI矛盾61で、2失敗runの実画像も陽性だった。ただし同一画像コピーは独立件数に数えず、これは方式選択の比較である。`evaluation/solo-direct-draw-transition-comparison-v1.json`等に保存。診断の保存後cleanup import漏れによるexit1は、保存済み比較値と区別して記録した。

陽性selfDraw直接確認版は対象178成功・最終44成功・通常ユーザー全回帰616成功4skip（112.94秒）、compileall成功で固定した。`evaluation/solo-basic-fixed-v4.json`、profile `artifacts/solo-basic-calibration-v5`、source `c3acec46294c7a6856038601a10785fcc41444923d6b0ab32c37f23ebc82a370`、components `9395f92ef04eb0b62a5e915ab5bae9dbfa1a809a1a3d940183bfce0fb67e3120`。画像資産・閾値は変更していない。lint/typecheckツール未導入。固定時点では新版実機成功0である。

次End準備では、公開詳細で雷龍融合を確認して手札上限の1枚discardを補助操作した。その対戦は相手の4攻撃でLOSEとなり、目的Endには到達しなかった。Retry1は発動候補のない初手で対象End応答が現れず、既承認のRetry2へ進んだ。これらの準備入力は`NEXT_END_PREPARATION_v4_20261006`へ保存し、E2E成功/失敗標本へ混ぜない。旧v2/v3の各1失敗は維持する。

## 共通固定v4のEnd実機成功1件

Retry2で相手Turn1End応答に到達し、新MSS・fresh preflight後、run `04e160524a544378b41f98e30ffa0d42` が成功した。証跡`artifacts/baseline-tester/SOLO_END_PILOT_v4_20261006/tester-review.json`。固定source/components一致、data_integrity true。実Cancel client(545,681)1回、seq0→18のruntime画像で青selfTurn2Draw・元応答なしをTesterとCoordinatorが独立確認した。今回は大帯ではなく旧badge陽性0.996829。prompt/animationはunknownを維持し、次入力準備完了とは扱わない。

成功E2E2527.866ms、内部union1610.495ms、poll906.303ms、verify内未計測5.170ms、その他未分類5.898ms。verify wall2383.605msは内部と重複、互換残差911.473msはpollを含む。capture累計492.403ms、recognition累計1021.406ms、predicate31.972ms、input21.762ms、artifact36.672ms。認識が内部最大の実測処理なので、次の性能調査はその内訳に限定する。残差を純ゲーム・通信待ちと呼ばない。

retry0/fallback0、独立観測misclick0/1。runtimeのmisclick nullは改変せずレビュー結果を別保存。旧v2/v3失敗は保持し、新版へ遡及換算しない。この1件は3秒以内だがp50目標2500msを27.866ms超える。標本1のため代表100件・成功率99%の達成根拠ではなく、他版のphase/normal実績ともcohortを混合しない。

## v4成功後の最大処理コスト測定と限定変更方針

実recognitionは19回、計1021.406ms、p50 54.347ms/p95 61.344ms/max74.389ms。現行は終了応答のverify中にも通常召喚用UIbank座標探索を毎回行っていた。保存before/after2画像だけの再生を`recognition-stage-readonly-replay-v4.json`に保存。全19画像の再現ではない。詳細wrapperは認識65〜85msとなる観測負荷があるため、その絶対値を実機削減量へ換算しない。

さらにcold2画像・10pairの順序反転で、無計装before59.346ms/after60.343ms、bank上位wrapperのみbefore58.215ms/after60.499ms、そのbank部分53.102ms/55.026msとなった（`recognition-observer-comparison-v4.json`）。約9割を占めるbankが最大コスト。registry/Caption/Drawの全面最適化へ広げず、実行中ledgerと宣言LogicalResponseDeclineが一致するverifyだけ通常召喚bank探索を省略する最小変更を承認した。

初回候補・通常召喚・phase・その他goalは従来経路、bank assetstat guardとgeneric全ROI/詳細registry/意味別全文/Cancel/Draw/既知prompt矛盾は維持。summon_enabled/hand_selectedはfreshunknownへ戻し、古いcache/座標証拠を再利用しない。bank子spanと親recognitionの重複はunionで除く。対象/全host回帰・保存画像比較・版固定後の新実機試験を必要とし、現時点で実機改善は未主張。

## 雷電龍の手札効果・自動サーチの実仕様収集

`DRAGONDARK_HAND_EFFECT_PREPARATION_v1_20261006`で有効効果メニュー10枚、その後`DRAGONDARK_SEARCH_TRAIN_v1_20261006`で同一MSS session seq0..59の60枚を取得し、元時計/hashを保存した。6段階は効果メニュー、自分雷電龍発動への任意チェーン問い、解決後未選択手札、追加後fresh手札inspect、GY一覧（旧detail残留）、GY実cardfreshinspect。収集は全て補助・訓練/仕様資料でE2E件数0、独立holdoutではない。

実際は発動1→任意chainCancel1→同名自動追加で、専用コスト選択とsearch選択/決定UIは出現しなかった。手札6→5→6だけを根拠にせず、左detailblank後の新手札click・雷電龍詳細・①使用済markを確認し、GYcount1の実cardを新clickしたhighlight/detailも別記録した。GY一覧を開いた直後の左detailは前の手札由来なので墓地identityへ流用しない。補助7入力（効果/Cancel/handinspect/GYopen/GYcardinspect/閉じ2）、閉じ初回で変化なしも保持。collector73328はseq59flush後exit0。新機能はこの観察済フローから設計し、未知の使用履歴や山札残数を真と捏造しない。

性能限定版は初回対象172pass/2failを保持。両失敗は保存画像のfresh時刻fixtureと相対registry pathのfixture不備で、production guardは維持して修正。対象174pass17.25秒、通常ユーザー全host631pass4skip117.14秒、compileall成功。保存2画像の20pair順序反転比較はcoldbefore57.907→5.838ms、after61.962→6.321ms、warm56.942→3.860/61.522→4.090ms。全response意味signature一致、assetstat約0.93〜1.07msを維持。実機改善量ではない。

固定`evaluation/solo-basic-fixed-v5.json` UTC2026-10-05T22:02:34.651953+00:00、baseは同じ`artifacts/solo-basic-calibration-v5`、source `f06abffb87445d4b5799e582e5839d1ea16839baf994e172810589b9397c4cf9`、components `1013228c37db2428c8d68ef6e88ef2890b1c92ea2093c5367f9e6316505a494f`。cal/route/UI/画像assetのhashは前版と同値。相手Turn3End保持から固定後新MSS→freshpreflight→最大1Cancelの新pilotを開始する。準備4補助入力と準備MSS3枚はKPIへ混ぜない。

## 共通固定v5の独立End実機成功1件

新MSS10/10とfreshpreflight後、run `9fd57910c8f5479097317f4106ebb92b` は1Cancelで成功した。保存先`SOLO_END_PILOT_v5_20261006`。実runtime after seq32は青selfTurn4DrawとDRAW PHASE帯、word0.943465/blue0.715278。TesterとCoordinatorが保存実画像で元応答なしと結果を確認。client(545,681)は適正Cancel、retry0/fallback0。

E2E2614.9034ms、内部union988.3830ms、poll1609.6701ms、verify未計測11.2151ms、その他未分類5.6352ms。capture累計667.7484ms/recognition235.7770ms/入力10.6146ms、normal_ui_bank子70.4443msは親recognitionへ重複加算しない。verifywall2490.0545msも内部と重複する。1件ではあるが内部処理は1秒以内だった。

前v4より内部622.112ms減、全E2Eは87.0374ms増。v4はseq18・帯なしDraw、v5はseq32・帯ありDrawで、フレーム数と盤面も異なる。同条件の因果改善量とは主張せず、再生比較と実機観測を分ける。今回もp50目標2500msを単発値では超え、100代表cohort達成ではない。旧失敗・異版成功を新cohortへ混合しない。

## 雷電龍の公開追加演出の連続MSS

元の60枚資料は解決中の連続MSSを含まず、freshdetail/usedmark/手札6→5→6だけでは元からの同名カードや無効を十分区別できなかった。追加資料`DRAGONDARK_REVEAL_TEMPORAL_TRAIN_v2_20261006/chain-cancel-reveal-continuous/manifest.json`では99/99eligible、seq20..118を取得。captureUTC2026-10-05T22:17:43.307899〜22:17:51.263291がCancel実API22:17:44.437〜44.551を跨いだ。入力前だけの撮影ではない。

実周期mean81.177ms/median82.708ms/max98.755msでPNG書込を含み、指定40fpsは未達。取得間隔を補完しない。Tester分類はindex0..17 chain18枚、18..21解決4、22部分公開1、23..26全文公開4、27..40移動14、41..98収納58。Implementerも原Native公開雷電龍のface→下方移動→slot接続を確認した。今回は手札7、旧資料は6で、配置差を分けて扱う。

新LogicalHandSearchConfirmationは独立typed goalとして、ACTIVATE→親発動に結び付いた自分雷電龍全文のchainCancel→公開incomingCID/手札slot接続→blank後実handinspectを1目的にまとめる方針を承認。旧normal/response型を手札用へ無理に転用せず、receipt/epoch/新sequence/sourcehash等の共通部品を再利用する。未知のunused/deckavailableは書換えず、表示された有効UIを根拠とするobserved_ui scope。usedmark/count/GYは補助で、成功の単独根拠にしない。全hash監査・実資料校正比較が成立してから最小実装し、未見のsearch選択UIは追加しない。

追加収集の最終報告は`DRAGONDARK_REVEAL_TEMPORAL_TRAIN_v2_20261006/collection-report.json`と`temporal-visual-labels.json`。総129/129eligible・全原PNGhash一致、同session seq0..128。入力API前16枚/区間内1枚/後82枚、full公開seq43..46/移動seq47..60/収納seq61..118、fresh手札inspectseq119..128。補助3入力/E2E0、collector62482はflush後stop exit0。Coordinatorも原MSS frame0025/0038で公開雷電龍faceと挿入先への下方移動を確認した。新レイアウトは手札7・slot3、旧6枚と無条件に混用しない。資料成立を受け、限定校正比較→専用goal最小実装→対象/全hostテスト→版固定をImplementerへ承認した。

## 次の攻撃scopeの不足調査

Researcher読取調査では、ActionType ATTACK/SELECT_TARGET、Action共通source/target/鮮度、PlanStep/expected_facts/typedloop/telemetryを再利用できる。一方ActionGeneratorの攻撃条件は表示UI・自turnBattle等に限られ、攻撃回数・禁止・合法targetを網羅しない。通常召喚専用UiCoordinateProofを攻撃へ暗黙流用せず、攻撃source/target対応と実戦闘結果の専用goalが必要。既存attack負例MSSは相手攻撃への任意応答で、自分の攻撃メニュー資料ではない。demo/phase制限testを実機攻撃成功とは扱わない。

雷電龍の実装と並行し、現在Soloの使用済み雷電龍保持後、手札Ash12950のfresh詳細と有効通常召喚UIを確認できる場合のみ、補助normal→空き自分中央→Battle→自分fieldAshの攻撃menu資料まで準備を承認。まだ攻撃宣言/対象選択は送らず、実UIを先に取得する。これらは準備操作でE2E0。未知強制選択や不在カードは勝手に置換しない。

## 雷電龍の追跡方式の失敗分類と採用

詳細CIDはカード画像ROI[27,151,103,150]→RGB64x96で比較し、初期参照1枚に対し残初期9＋fresh最終10の最小score0.9999619、既知別CID52の最大0.9012768。固定0.98で分離したが訓練比較であり未知全カード/独立holdout精度は未証明。手札小画素からCIDを付与せず、所属は別の実入力/新seq/geometryで結ぶ。

単一参照のsparseLKはframe27の大下降で有効点0となり失敗を記録。小ROIのcoarse位置/scaleを初期値にすると27を通過したが、frame30で有効5点となり拒否した（`dragondark-coarse-initialized-continuity-v1.json`）。Coordinatorが原frame30とrows28/29を比較し、y約600→596→560という持上げ演出と下限dy-8の仮定不一致を指摘。単なる光の影響と断定せず、画面上の実軌跡を確認した。

`dragondark-staged-entry-raise-storage-continuity-v1.json`では、entered後だけ上方-50pxを許可しraised確認後-8へ戻す段階モデルを採用。FB1.5/RANSAC2/min6/inlier比0.7/scale/dxの照合品質条件は維持。frame25公開→27下降24/24→28入場20/20→30持上げ7/10→31..40各7/7→41格納7/7、bbox41[589.3,595.2,102.8,151.6]で必要な履歴が成立した。42の部分遮蔽による棄却は保持し、全99枚成功を目的にしない。未観測を補完せず、陽性公開anchorから格納slot＋別実inspectへつなぐ専用goal実装を開始した。これは方式選択資料で、実機成功数へ換算しない。

## 攻撃宣言・対象確定・戦闘結果の実資料

`ASH_ATTACK_PREPARATION_TRAIN_v1_20261006`では補助7入力で通常召喚からBattleの実Ash攻撃menuへ進み、7stage70枚を取得。次の`ASH_ATTACK_RESULT_TRAIN_v1_20261006`で、攻撃宣言→2体がyellow選択可の対象UI→左1900/1500の甲虫装甲騎士選択→一意の「決定」を観察した。対象クリックだけでは戦闘開始しない。最初の連続100枚は対象選択の資料として分離し、完了と偽称しない。

決定後の別連続102枚で戦闘を収集し、実最終画面はselfTurn4Battle、LP3700→1800/相手8000不変、自中央Ash消失・自場empty、相手甲虫装甲騎士1900/1500と中央2400/2000残存。Coordinatorも008-battle-final-state.pngを独立確認。補助3入力（attack/target/confirm）、攻撃再送0、追加prompt0。これは戦闘結果の仕様資料で、戦略上有利な結果とは扱わず、runtime/E2E件数0。最終MSS/UTC被覆/全hash監査はTesterが別途完了させる。

攻撃収集の時刻監査で訂正：最初の連続100枚はcapture22:50:28.612〜36.614Zに対しtarget API開始22:50:46.225Zで、ツール遅延により全て入力前だった。対象入力を覆った資料ではなく、preinput-onlyの計測手順失敗として保存・分類訂正し、後続画面で欠測を埋めない。第2の決定burst102枚はcapture22:54:36.146〜44.149Zに対しconfirm API22:54:37.294〜37.414Zで被覆成立。最終MSS10はseq232..241、collector84819stop exit0。入力前から固定8秒の終了へ依存する手順は再利用せず、今後はinputtool/可視完了を覆う長寿命の上限付き収集へ改める方針。今回は有効な決定後資料と不足した対象遷移を分離して報告する。

攻撃最終reportは`ASH_ATTACK_RESULT_TRAIN_v1_20261006/collection-report.json`/`temporal-visual-labels.json`、全242/242eligible・全原MSShash一致。target選択後の別10枚seq120..129、決定入力を覆う連続102枚seq130..231、最終後状態10枚seq232..241を分離保存。第2連続のindex59..101に実最終結果43枚。第1連続はmean80.838ms、第2は79.231msで40fps未達。第1preinput-onlyの訂正リンクと手順失敗を残しrawmanifestは改変しない。collector84819はseq241flush後stop exit0。現在BattleLP1800/自場emptyで追加操作せず保持し、雷電龍の実装を優先する。

## 100件集計の分母・初回認識失敗の監査

Researcherがtelemetry.pyのfinish/summarize/MeasuredCapture.readを読取監査。finishは失敗/timeoutもcapture_start→ended_atのtotal_msを保存し、成功専用時刻のみnullにする。summarizeは全live目的を成功率分母と全試行時間統計へ含め、成功例統計は別欄。誤クリックの独立review未完は率null/gatefalseであり0扱いしない。retry/fallbackも全目的分母、登録trial/slot/provenance一致を要求する。一方、retry/fallback計装の漏れ検知、意味的判断ミス全般、カテゴリの頻度代表性は別の独立監査が必要。

MeasuredCapture.readはsource.read前にadmit(clock)しscheduledtrialをactive化するため、最初の画像取得/認識失敗や候補0のtimeoutも失敗として計上される。未開始trialは未消化でgatefalse。not_eligible/not_observedの自動分類はなく、実条件不成立と認識失敗の区別は独立画面レビューを要する。

ただしpilotで使用している別read-only preflightはtrial台帳へ時間・失敗が結合されていない。最終100cohortでは、GUI上eligibleのpreflight認識失敗を先に除外して成功runだけを登録してはならない。画面内容に依存する最初の評価からtrialを開始し、preflightを含めるなら開始時刻/拒否/再試行を同台帳へ結ぶ必要がある。別案は環境・資産のみのpreflightを固定前に済ませ、cohort内の全画像評価をMeasuredCaptureのadmission後に行う。現pilotを100cohortへ遡及換算しない。実装・運用でこの条件を満たした証拠ができるまで最終合格にしない。

## 新手札searchの接続中レビュー：手札全体RGBへの過適合

Coordinatorが新hand_search.pyと`artifacts/dragondark-hand-search-calibration-v2/hand-search.json`を読み、source/selected ROI[320,540,650,180]、ready ROI[320,595,650,125]が手札帯全体のRGBを条件にしていることを確認した。これは他の手札カードの絵柄にも依存し、hand geometryだけの証拠ではない。

新準備`DRAGONDARK_PILOT_PREPARATION_v1_20261006/ready-effect-menu/frame-0000.png`をpixelsだけのSimpleNamespaceでread-only recognizeした（時計・live provenanceの付与なし/入力0/exit0）。detail0.981049→CID13906、effect6 0.994480は成立するがsource6 0.892222でsource_layout null。同じ手札6-slot3の有効menuを他の手札構成で拒否した。準備画像は固定前の方法選択資料で、独立holdoutではない。

この過適合を新しい手札全景の参照追加や閾値緩和で埋めず、sourceを相対hand geometry・明示effect UI・詳細CIDへ結び、ready/selectedも公開episodeの実bboxと局所形状/freshinspectへ結ぶ限定修正をImplementerへ指示。旧modal不在の床色proxyと同様、意味を確認したい対象から無関係な背景/他カードへの依存を外す。接続中の部品の修正であり全面再実装は不要、旧型/既存成功結果は維持する。

### 雷電手札局所形状修正の中間レビュー（2026-10-06）
Coordinator が現行 HandSearchVision を pixels のみで read-only 再生。DRAGONDARK_PILOT_PREPARATION_v1_20261006/ready-effect-menu/frame-0000.png は以前 source hand-band RGB .892222 により棄却されたが、局所形状版では source_layout=hand6-slot3、bbox=[639,586,93,94]、detail_score=.9810489416、own_chain=false、gy_panel=false。終了コード0、入力0、画像・原時計変更なし。方法選択資料の再生であり、holdout/実機成功/E2Eには数えない。実装・テスト・版固定は進行中。
Researcher の現行コード監査では、tracker は dt<=300ms とフレーム間移動 dx±40/dy[-8,120]（entry raiseのみ下限-50）を別に制限し、校正約81msと実runtimeの50ms poll+capture+recognition間隔の同等性は未証明。公開anchor欠測、raise段階の飛越、途中chain表示、handoff後鮮度の境界を試験する必要がある。現段階で hand_search を直接参照するテスト未発見のため、Implementerへ新goalテストに含めるよう通知。速度改善や完成とは判定しない。

### 正式評価の preflight 母数保持：実装前の接続案（2026-10-06）
Researcher が現行 helper/CLI/telemetry を再調査。独立 scripts/preflight_solo_response.py は trial 無しの pilot loop を作り画像を評価して閉じるため、これを acceptance の成功フィルタにすると拒否試行が目的母数に入らない。最小案は画像判定を frame/state/action を受ける pure check に分け、AgentLoop.run の初回 MeasuredCapture.read による admit 後、同じ telemetry active 内で実施する。合格後も最初の capture_start を保ち、古くなった画像は同目的内で再取得する。別runの時計を後付け結合しない。
必要な受入確認：(1) capture例外を入力0の失敗としてtotal付き記録、(2) 画像上eligibleだが認識/候補0を母数に保持、(3) 合格から実入力/結果確認まで同trial1件・最初取得起点、(4) 拒否後の同slot成功再実行で元失敗を置換しない、(5) 前面/epoch/timeout拒否と未開始slotを区別して未消化gateを維持。既存 test_telemetry.py の pre_admitted_capture_failure、failed_trial_without_candidate、trial_manifest_denominator が拡張候補。画像を使わないsetup検査と実試行を区別し、setup中断のslot台帳も必要。これは提案であり未実装・未検証。現在の手札効果pilotを先に完了し、正式100件の開始前に対応する。

### 手札効果実装中の既存機能回帰（2026-10-06）
Coordinator が作業中版へ read-only テストを実施。test_strategy_rules.py + test_telemetry.py は88 passed/1.95s/exit0（evaluation/root-hand-interim-tests-20261006-a.xml）。test_agent_loop.py + test_response_decline.py + test_response_verify_scope.py は90 passed/8.95s/exit0（evaluation/root-hand-loop-interim-20261006-a.xml、session94683終了）。合計178件、sandbox内、新規workspace basetemp、pytest cache無効。既存機能の互換性確認であり、新しいhand-search固有境界・host全回帰・実機E2Eの代用ではない。版は未固定で、Implementerへ結果共有済み。

### 雷電追加表示の原時計による所要時間参考（2026-10-06）
Researcher が DRAGONDARK_REVEAL_TEMPORAL_TRAIN_v2_20261006 の原JSONをread-only算出。Cancel API開始22:17:44.437Z/終了44.551Zに対して、公開face global43の取得開始45.039942Zは488.942～602.942ms後、44は575.968～689.968ms、45は657.547～771.547ms、46は742.442～856.442ms。handoff候補global61の取得開始46.594036Zは2043.036～2157.036ms後、当該取得duration16.3702ms。同perf時計のglobal43→61取得開始差1554.1248ms、46→61は1300.7579ms。API区間は実OS入力時刻の確定boundsではない。monotonic captured_atとの差分1546/1296msとは時計/粒度/起点を混ぜない。
この資料は補助入力後の表示過程のみで、ACTIVATEからの目的E2E・純ゲーム通信時間・性能達成の証拠ではない。手札格納まで約2秒規模の観測が必要だったことを示す参考としてImplementerへ共有し、pilotのtimeoutを3秒KPIそのものにせず実結果まで計測する方針を維持。

### 次の攻撃goalの接続案（2026-10-06、未実装）
Researcher が取得済 ASH_ATTACK_RESULT_TRAIN_v1_20261006 を現行typed goal/receipt/routeへ対応付け。ATTACK→SELECT_TARGET→CONFIRMを1つのLogicalAttackConfirmationとして扱い、公開source CID/zone、有効攻撃UI、対象選択全文prompt、同zoneの選択表示＋実選択後fresh target detail、3入力receiptと新frame、戦闘後のsource不在/target残存/LP変化を組み合わせる。対象資料でAsh破壊・相手残存は戦闘実行成功であり、攻略判断の妥当性とは別。LP変化単独・残存detail単独で成功としない。座標proofはnormal専用型を流用せずfresh client/epoch/frame/bboxの範囲を持つ。
資料のLP3700→1800/相手8000は観測値。Coordinatorから、同じ公開Ash攻撃0対1900の限定条件でもruntime初期LPを固定3700にせず、実beforeから1900減/相手不変という相対判定候補と分離するよう指示。別初期LPでの実機成立は未検証、未知効果/攻撃無効/別対象へ一般化しない。失敗receipt/別zone/旧detail/LPのみ/守備/直接攻撃のnegativeを必要とする。既存242枚は補助訓練E2E0で、対象click burst100は入力前のみという欠測を維持し、CONFIRM burst102の遷移と混同しない。実装候補はstrategy_rules/route_validation/perception/agent_loop/telemetryと限定profile。手札goalの固定・pilotが先で、同時編集しない。

### 手札効果の固有不具合再現テスト（2026-10-06）
実装工程を小さく分け、Implementer が tests/test_hand_search.py を作成。実行15件は9pass/6fail、終了コード1、evaluation/hand-search-reproduction-v1.xml（XML tests15/failures6/errors0をCoordinator確認）。実装修正/host全回帰/版固定は未実施。原画像・原時計変更0、実機入力0。実画像を使うfixtureのreceipt/live wrapper/clock/epochは明示的syntheticで、実機成功としない。
失敗6件はready6の可視・傾斜カードを検出できない、unselected6の背景横線をselectedカード上辺に誤採用、handoff後expired/same-seq/older-seqの3条件をearly returnで未検査、300msちょうどを浮動小数差で超過判定。source3scene・selected7・epoch変化拒否・299ms許可/301ms拒否・anchor欠測時handoff未生成は通過。次工程を6失敗の最小修正と同15件再実行に限定してImplementerへ開始指示。成功に合わせた大幅閾値緩和やwholehandRGB再導入はしない。

### 手札追跡の時間・順序修正の中間確認（2026-10-06）
現行hand_search.pyにhandoff後の単調sequence/取得時刻、handoff最大経過、数値誤差を考慮した時間境界判定が追加された。evaluation/hand-search-time-fix-v1.xmlをCoordinatorが読み、選択実行9tests/0fail/0error/2.629sを確認。15件全通過ではなく、形状2件は継続修正中。
Researcherのreceipt結合監査では、型・3child順序・同spec・実送信・fresh detail・anchor/handoff順序の既存拘束を確認。一方、第3child beforeのresult_ready陽性とinspectpoint↔handoff bboxはAgentLoop座標解決には拘束があるがtelemetry validator単体では再結合が薄い。また同specでも別logical_actionのruleと親activeを直接照合する境界が不足。次integrationでmissing receipt/旧detail/別goal/anchor前後不正/異なるpointを拒否する試験をImplementerへ通知。形状修正を先行し、未検証の新goal成功や実機E2Eとは扱わない。

### ready6実画像の遮蔽レビュー（2026-10-06）
Coordinator が DRAGONDARK_SEARCH_TRAIN_v1_20261006/post-search-hand-unselected/frame-0000.png を直接目視。対象Darkの右側が隣の手札カードに重なるため、ready状態で完全なカード矩形を要求すると、傾きだけでなく遮蔽でも拒否し得る。目視のtop約606/left約633/隣card左約714は概算で閾値根拠にはしない。
Implementerへ、readyはactual handoff bboxに結び付いた可視部分と安全点として扱い、source/selectedの完全枠条件を一律に緩和しない方針を通知。必要ならready6の再現testを一般rectangle APIから役割別ready APIへ接続してよいが、背景線・別bbox・隣cardのnegativeは維持し、要求の変更理由を残す。修正・新test結果はこの記載時未確認。

### 連続画像間引きによる追跡感度（2026-10-06）
Researcher が v2連続資料を4パターン各1回メモリreplay。元99画像SHA全一致、元captured_at_monotonic/sequence保持、保存/GUI操作0。Frame live wrapper・input receipt・epoch42はsynthetic、KPI外。Cancel before_sequence36、global>=37から開始、local indexは元burst index。source前後SHA一致7c8d0a15383ad656e4a4dfcfc119ff3f8459295054e7a8a7d62dbcad1747983a。
全frame：25観測/maxgap110ms、anchor43→handoff61成立・点9。偶数local：6観測/maxgap172ms、anchor44後track_points_under6失敗。奇数local：13観測/maxgap188ms、anchor43→handoff61成立・点7。local%3=0：9観測/maxgap282ms、anchor44後track_points_under6失敗。handoff最初成立または失敗で各patternを停止。
両失敗は300ms時間上限ではなく対応点数不足。観測間隔とanchor位相/画像列への依存を示す同校正資料上の参考で、実runtime成功率や速度優位の証明ではない。Implementerへ共有し、pilotのframegap/anchor/failure証拠を保持する。現時点の形状修正scopeを広げず、実機baseline前に推測で最適化しない。

### selected背景線の誤接続修正（2026-10-06）
Implementer が local_card_rectangle の edge-strip縦辺延長を除去。実Hough線分の交差だけを使い、欠落辺を背景まで補完しない最小変更。既存Canny/Hough/接続/幅の閾値は維持。evaluation/hand-search-shape-line-fix-v1.xml は選択5tests/0fail/0error/time0.929sをCoordinator確認（agent報告pytest0.97s/exit0）。source実3scene、selected7陽性、unselected6背景線negativeを含む。
時間系9件は別の通過証拠。全15件通過ではなく、ready6遮蔽の役割別可視部分APIは残件。CoordinatorがコードとXMLを確認し、handoff付き可視部分の実装→全15と別bbox/隣cardnegative→integrationの順に継続指示。

### ready可視部分APIの初回検証（2026-10-06）
新ready_visible_cardはCIDを生成せず、handoff bboxに沿う可視上辺/左辺と内側安全点を返す役割へ分離。元hand6連続handoff欠測のため当該bboxはsynthetic局所fixtureと明記。初回18testsは17pass/1fail、exit1（evaluation/hand-search-shape-ready-v1.xml、XMLtime3.579s/pytest報告3.62s）。失敗はready6陽性だけ、追加3negativeと他14件は通過。失敗結果は保持。
Implementer報告の可視線は左[637,715→640,606]・上側[625,614→707,620]。内部斜線の影響を避けるためhandoffに沿う上辺帯/左辺帯の別抽出を次に検証する。Coordinatorは実コード/XMLを確認し、可視safe bbox/pointをPerception/座標proofへ渡し、旧handoff矩形中点の再計算で安全点証拠を失わないよう同工程の接続修正を指示。未検証であり実機成功を意味しない。

### ready可視部分APIの通過（2026-10-06）
evaluation/hand-search-shape-ready-v2.xmlをCoordinatorが確認し、18tests/0fail/0error/time3.503s。hand_search.pyの実変更はhandoff左端/上端に沿う帯でCanny/Houghを別抽出、収納fanに限定した傾き8px/上端16px、接続線から可視内側bbox/pointを生成するもの。source/selectedの厳密矩形条件は緩めない。v1失敗XMLは保持。
これは形状・時刻の限定テスト通過であり、Perception→proof→実座標の接続と3child receipt integrationは次工程。Coordinatorはsafe pointを旧handoff中心へ置換しない接続、same-spec別logical目的、第三childready欠測/違うpoint、旧detail/missingreceipt/newsequence、正常3childの検証を指示。host全回帰・版固定・実機pilot・100件評価は未完了。

ready-v3追記：可視API→Perception proof→AgentLoop座標validatorを接続し、tests/test_hand_search.pyは22pass/pytest4.94s/exit0（evaluation/hand-search-shape-ready-v3.xml）。追加4境界は正しいsafe point、別point、別bbox、旧geometry。Coordinatorが実テストと接続コードを確認。座標はsafe bbox/pointの同値と同frame seq/monoを要求し、handoff全体からの中点再計算を廃止。実入力0であり実機操作成功ではない。次は3child receipt結合integration。

### hand-search実機runner接続のread-only監査（2026-10-06）
ResearcherはCLI build_pipelineがrouteのlogical_hand_search_confirmationからconfigure_hand_searchへ接続済みであることを確認。専用--hand-search-profile引数は存在せず不要。現行v3のcalibration.json/solo-route.json/ui-rules.json/hand-search-trials.jsonを既存agent引数へ渡す構成で、実rect/output/既存DB等の実引数は固定時に検証する。
不足は(1) preflight_solo_response.preflightがlogical_response_declineのみを判定しhandをpassedにしないため専用checkが必要、(2) AgentLoop.guarded_scopeが旧inspect/response依存でsolo併存時には有効でもhand単独を明示していないため、手札専用でもepoch/rect/client guardを保つintegrationが必要、(3) 旧固定版は使用不可で新handassets/module/helper/route/UI/limits/DBを含む固定manifestと固定後fresh確認が必要。現時点の調査は実機起動/画像取得なし。Implementerへreceipt工程と次runner工程の残件として通知。

### 3child receipt結合の初回再現（2026-10-06）
evaluation/hand-search-join-v1.xmlをCoordinatorが確認：16tests/8fail/0error/time0.342s、agent報告exit1。正常3childは通過。失敗negativeはsame_spec_other_goal、third_ready_missing、different_safe_point、different_handoff、stale_before_detail、blank_missing、neighbor_selected_geometry、missing_selected_geometry。合成履歴による検証で実入力0。
Implementerのbegin_step第三前episode snapshot、同目的/ready/blank/実point↔handoff↔現在選択形状のANDを追加する最小案を承認。旧fail XML保持。guarded_scopeについてはResearcher調査時の版から既にhand_goalを含む版へ変更済みとImplementer報告、単独hand guardテストは残件。この訂正を維持し、未接続と断定し続けない。

### hand-search証拠結合の修正後通過（2026-10-06）
evaluation/hand-search-join-v2.xmlをCoordinator確認：38tests/0fail/0error/time5.216s。shape22＋receipt16を含む。telemetry.hand_step_confirmedは親logical_action一致、第三前episode snapshot、ready/blank、safe bbox/point、同handoff/seq/timeと結果selected形状を結合する修正が入り、初回8negativeを拒否。rootが実コードも確認。syntheticの統合テストであり実機成功ではない。
次工程としてhand単独guard/実CLI構築、hand用freshpreflight/runnerを確認し、target→host全回帰（新規workspace temp・cache無効）→compile→新source/assets/helpers固定をImplementerへ指示。実機入力はTesterによる固定後pilotのみ。100件未達。

実行scope追記訂正（2026-10-06）：Implementerの追加確認とrootの現行コード確認により、guarded_scope propertyはhand対応済みだが、__init__内local guarded_scopeは旧inspect/responseのみであった。前記『既に変更済』はpropertyだけを指し、手札単独のlive binding全経路完了ではない。次工程でconstructor側も修正し、native/offline双方のhand単独guardとCLI/helper接続を試験する。receipt38件通過後compileall exit0の報告あり、host全回帰/版固定は未完了。

### 実行接続テストとfixture不備の修正（2026-10-06）
runner-v1 XMLは43tests/4fail/time12.886s、3件は合成Action.confidence必須値欠測、候補Noneの1件はsynthetic captured_at=1秒を実decision clockの鮮度guardが正しく拒否したもの。Implementerはfixture confidenceを1、明示synthetic wrapper時刻をdecision clockに合わせて修正し、元保存metadata/画像とproduction許可条件は変更なしと報告。runner-v2 XMLは対象5tests/0fail/time8.180sをroot確認。保存画像を実機成功に換算しない。
CLI --verify-secondsを追加、既定3秒を維持し今回の診断hand pilotは観測上限8秒予定（性能KPI3秒とは別）。constructor hand単独native/epoch guard、trial事前登録、共通evaluate/preflightのhand開始判定が接続された。freeze helper/timeout境界追加後のtarget+telemetry回帰はsession79768実行中と報告。初回target-v1は不存在test_cli_args.py指定でexit1/実行0、履歴保持して正しい既存testへ修正。host全回帰・固定・実機pilotは未完了。

### 全回帰開始と固定前idle再監査（2026-10-06）
対象107件pass/14.48s/exit0（hand-search-target-v2.xml、root XML確認）。通常ユーザー全suiteはsession74073、新規workspace basetemp/cache無効で実行。rootはPython PID29980の稼働を確認し同sessionへ競合pollしていない。freeze_hand_search.pyをread-only確認し全src/scripts/tests/校正asset/DB/routeとlimits（8秒verify、3inputs、20秒総上限、retry0）を新snapshotへ固定する構成を確認。
固定前の再監査で、ready/selected scene＋Main1からui.animation=Falseを生成する旧作業中処理が残存とImplementer報告。現在host結果を保全後、この2sceneの根拠なしidle生成を除外し、実資料で既存陽性idle条件を測定する限定修正を承認。known_main1_clearの具体条件を確認し、床RGBproxyへの逆戻り・未知false化・一般guard緩和を避ける。必要ならunknownを維持した手札inspect専用の操作証拠を検討するが、この記載時は未測定・未実装。最終版固定/実機pilotはこの修正検証後。

host-v1結果追記：676pass/4skip/pytest111.56s/exit0、session74073終了。ready6/7再生の既存known_main1_clear条件は phase_context.self_main1（両unknown）＋clear_center（.98887/.98813）＋clear_card_menu（.98477/.98478）で、全体idle陽性にならない。第三SELECT_CARDだけactual parent/Cancel receipt、同episode/handoff、fresh result_ready、陽性detail_blank、同frame可視safe point、現在selfMain1の既存要求を根拠に許可し、animation Noneを維持・True拒否とする最小案を承認。source/CANCEL/他Actionは不変、別prompt拒否。手札7資料はinspect_context.main1もunknownで全contextcoverage未成立、手札6は.997813で通過。形状CIDの対応と全操作対応を区別し、新assetで今回scopeを増やさない。変更後専用境界＋target＋最終hostを要するため、host-v1は最終固定版の証拠ではない。

### unknown animationを維持する限定inspect判定（2026-10-06）
対象hand-search-target-final-v1.xmlは147tests/0fail/0error/XMLtime15.917s（pytest15.93s/exit0、session8815終了）。rootがXMLとunknown保持10境界/UI規則4境界の実テストを確認。playing/別Action/source/prompt/古proof/ready・blank欠測/矛盾animationは拒否し、第三手札inspectだけunknownのまま許可する。座標側でも親ACTIVATE→CANCELの実receipt/epoch検証/changed/同episodeを要求する追加と、UiPolicy欠落時の一般strict推薦fallbackを防ぐ一意3child規則の起動時検査をImplementer報告。
現手札6readyの全Pipeline再生と親receipt座標negativeを補完してからsource変更を止め最終hostへ進める段階。147通過は最終固定/実機成功ではない。旧host676passは追加修正前の証拠として保持。

### 最終接続回帰と第一追跡失敗フレームの監査（2026-10-06）
補完64tests/0fail/17.208s XML確認。ready6全Perception→strict filter→UiPolicyがanimation=NoneのままSELECT_CARD/safe pointへ接続し、親欠測/別episode/Cancel未送信/別regionを座標guardで拒否。host-final-v1はXML699total/4skip/0fail（695pass）、120.501s、PID31448終了をroot確認。
固定前にrootが_verifyを確認し、hand_step_confirmed false→continueがepisode.failedの永久失敗でもtimeoutまで回り、保存画像が第一失敗時でなく末尾になり得ることを指摘。既知の間引き点数不足を実機で診断できるよう、first failed frame/seq/mono/reasonを既存failure経路で保存して終了する最小対応の必要性をImplementerへ確認依頼。成功hotpath同期I/O追加なし、後刻画像の代用なし、元host結果保全。必要変更がある場合はその対象検証/必要回帰後に新固定とする。まだ実機pilot未実施。

### 第一追跡失敗の保存処理テスト通過（2026-10-06）
hand-search-first-failure-v2.xmlは87tests/0fail/0error/time16.531s、exit0と報告。rootがXMLと_verify/保存経路を確認。合成試験でseq2 track_points_under6の実frame/mono/hashと、直前seq1をbefore_hand_failure別roleで保存、seq3を取得せず終了。8秒timeoutとは記録せずRecognition failure eventと実reasonを保持。成功経路の同期I/Oは追加しない。
初回の1失敗はsynthetic100×200の縦横比を正常拒否したfixture不備でnative1280×720へ補正、旧XMLを保全。freeze limitsのint/float表記とCLI value_hash一致もテスト済みと報告。最終full session16858/Python27708稼働をroot確認、source変更停止。完了回収→compile/freeze→固定後Tester pilotが次段階。

### 雷電手札pilot版固定とTesterへの引渡し（2026-10-06）
最終host-first-failure-v1は701total/4skip/0fail（697pass）、XMLtime109.185s/pytest109.21s/exit0。session16858終了、compileall src/scripts/tests exit0、ruff/mypy/pyright未導入。固定evaluation/hand-search-fixed-v1.json、UTC2026-10-06T00:56:20.097727Z、819filesをroot確認。
source292c4502cd5afbcb38a0a62437bafdd19be9307695f835e0cfec14fe2566c66c、components144fb41ae6ef18aef86585a651fb7073cfd5ae3ff601e378cdfd0d075737b579、rawcal21cb96f51c4d159e6f2f55e5ae306fc0d42b86af0cdc8eeb2775130b7426be9b、route935cb1133d7fe1e068f54d6181a940b6b0b89571cd50cbe8b891a41c170bada3、limits715f20c2c8795dd20e5e2b2be4b14c67d780e0dbdcd9e0fdd2e552c19456a5b2、handprofile4461e76ea0d62a421e473460cfcb7a35e4a1824479bbb8ee3574bac1b793eb33。base artifacts/dragondark-hand-search-calibration-v3。
Testerを再開し、固定後newMSS10→freshpreflight→通過時1目的/3child上限pilotを指示。exact evaluate/preflight/agent-loopコマンドをImplementerから受領、rectは現在native実値へ照合。total20.0s/verify8.0s/poll.05/settle0/retry0、8秒は診断観測上限でKPIと別。新出力DRAGONDARK_SOURCE_TEMPORAL_FIXED_v1_20261006、DRAGONDARK_HAND_SEARCH_PREFLIGHT_v1_20261006、DRAGONDARK_HAND_SEARCH_PILOT_v1_20261006を予定。source/assets/helpers停止維持、未知/失敗を手動救済せず保存、CLI exit0を目的成功と混同しない。正式100件には算入しない。記載時pilot結果未確認。

### hand v2実機失敗と到達段階（2026-10-06）

v1固定後新画像10件の開始認識は0/10で入力なし。色変動に対してdetailの固有art照合、選択手札の同art所属を追加したv2は、full host748pass/4skip（evaluation/hand-art-host-v2.xml）、固定後の新MSS開始10/10とfresh preflightを通過した。方式選択に使用した旧画像の再生は独立実機評価に数えない。詳細履歴は.agent/PLANS.mdとevaluation/source-art-*に保持。

v2実機run a1797ba960b648fa9cb43e4adfaaef0eは登録1目的・成功0、ACTIVATEのみ1入力、time_limit/interrupted、total20201.076ms。CLI exit0は目的成功ではない。固定source e6260451be5aa37c539de0c38788cc5ce519c9d414e25c73d782112bf6e869adとcomponents a6b750415732a3b9daebac49b01d31907f2a1a725121815183b155e4ab4d71faは前後一致。Tester独立レビューの誤クリック0/1、retry0、fallback false。原runtime misclick nullは変更しない。原証跡はartifacts/baseline-tester/DRAGONDARK_HAND_SEARCH_PILOT_v2_20261006/tester-review.json。

seq20で自己雷電chainを確認して第1childはchanged。しかしMain1 raw .958639<.98で、現在Main1を要求するhand helperが専用Cancelを生成せず、その後93回abstain。Implementer読取診断では旧chain資料も同Main1 .966355/.966889で不成立。通常画面用templateのcoverage不足を、閾値緩和やunknown phase/animationの偽補完で修正しない。親ACTIVATEの実receiptと現在fresh exact自己chain/enabledCancelに限定する接続、およびoverall time_limit時の既存最終runtime frame保存を実装担当へ許可した。記載時は未検証。

total内部13881.536ms、認識8585.520ms、取得3885.630ms、poll1006.002ms、verification未計測14.374ms、未分類5299.164ms。normal UIbank6908.868msは認識の内数。最初のverify5526.059msだけでは内部4505.683ms、認識2104.551ms（20回）、bank1752.735ms、取得1288.883ms。残る後続abstain区間と混ぜて第1操作のコストを誤記しない。未分類やresidualは純粋なゲーム/通信待ちの実測値ではない。

after-0001.pngは第1child中間seq20であり、20秒時点の最終画像ではない。overall time_limit最終runtime画像は欠測。後刻Sky画像による代用なし。別の手札6枚chain→収納訓練は補助操作として分離し、元失敗目的を成功へ再開換算しない。

マイルストーンは①調査/計測基盤済、②基本操作の個別成功あり、③複数操作連携の実機修正中、④手動準備の自動化と特殊召喚/攻撃/周回の接続未完、⑤同一条件100目的の正式評価未開始。異版phase約0.58〜0.62秒、Ash通常召喚2.335秒、End辞退2.615秒の個別成功を合算したKPI達成主張は禁止。

次の探索prefix設計はResearcher読取調査済。初回telemetry.admitのcapture_startと同parentを維持して複数inspectを含める。prefix_stepsと実行3childは検証上分離するが、総時間/入力/誤操作/試行分母には両方を含む。未選択手札の実可視bbox・非被覆点・frame/epoch/client・instance_key・layoutrevisionを持つ専用proofが必要で、既知中心/handoff用検出器を汎用手札検出済みとは扱わない。未知CIDは発動禁止、曖昧同名instanceは停止、re-fan/増減/外部入力で位置cacheを破棄する。未実装設計であり現在のownchain修正へ同時混入しない。

### hand6の連続実画像を追加取得（2026-10-06、補助訓練）

DRAGONDARK_HAND6_CHAIN_REVEAL_TRAIN_v3_20261006/chain-cancel-reveal-continuousのmanifestをroot確認。397枚seq5..401、取得UTC02:57:02.285..32.285がCancel API02:57:12.729..12.835を包含する。API呼出し区間はOS入力イベント時刻ではない。補助Cancel1回とfresh手札inspect1回のみ、発動再送なし、元pilot失敗は保持。rootは005画像で手札6枚・fresh雷電詳細・使用済み表示・Effectメニュー無しを確認。

Researcher独立目視ではseq157で公開雷電の移動、seq159..161で中央fullface、seq162..163下降、seq164でfan内、seq166再せり上がり、seq167..175でhighlightを確認。seq180の別cardback演出を雷電追跡へ無条件に混入しない。確認した境界画像の原hashは一致。これはtracker自動認識成功ではなく、原画像の独立目視結果。

前面条件だけのeligibleはindex0..333の334枚。Cancel後の同一入力epoch97996062区間はseq151..315に限る。seq316以降は前面がゲームでもepoch変化/前後不一致があり、同episodeの追跡検証へ混ぜない。seq339..401の末尾63枚はforeground197964でquarantine。Tester報告の実周期mean75.758/median74.763/max111.095msは保存付き訓練収集の値で、runtime取得性能とは区別する。

実終了理由はbounded_time_limit。目視収納後のstop markerはUTC02:59:05.670で収集終了後に到着したため、視覚イベントで即停止したとは記録しない。訓練E2E0。現trackerの診断は同epoch適格区間へ限定し、原clockを保持して実施するよう実装担当へ依頼。元資料をrefへ追加する前に現方式の結果を確認する。

root独立hash監査：own-chain-before5枚、continuous397枚、post-storage-fresh-hand-inspect5枚の計407枚すべてが元manifest SHA256に一致、欠測0。post-inspectはseq402..406の全5枚がeligible。画像ファイルの完全性と自律動作の成功は別条件であり、この監査によるE2E件数追加はない。

### 自己chain再現テストと追加のanchor不足（2026-10-06）

own-chain-reproduction-v1.xmlで実seq20画像の専用prompt未生成を1件再現。新parent_activation_ui分岐の初回実装はcaption初期化欠測で1fail（own-chain-impl-v1.xml）、修正後own-chain-impl-v2.xmlは1pass/2.361s。これはsynthetic active-parent fixtureを使ったPerception再生であり、終了済み元trialの再開やruntime成功ではない。root途中reviewで、新modeでもMain1陽性時に旧branchへ逃げる可能性とanimation=False提案を指摘し、旧defaultを維持しながら新modeを独立させる負例を依頼。全経路/負例/最終hostは未完了。

Researcherに現trackerの新hand6原時計診断を移管。hand6-tracker-original-clock-diagnostic-v1.jsonはseq151..315の165枚を順に処理し、anchor/handoff無し、failed無し、trace0/readyfalse。synthetic入力receipt/live wrapperを明記し、原clock/seq/hashを保持、実入力/E2E0。永久failureまたはhandoffで止める方針だったが、どちらも発生せず範囲末まで処理。手動ラベルで追跡を注入しない。診断source前後d935ee6c8c760a02a3928fc21f370c0ed00bc2d9797cc0bea6502d8bf80bfbea一致。

hand6-anchor-score-diagnostic-v1.jsonで入口を分離。seq157..163はownchain/GY/epoch/client条件が通り、各best候補のfeatures24。4参照×3scaleのbestNCCは順に.254628/.843458/.941228/.975090/.954087/.213166/.264764、すべて.98未満。最高seq160 bbox[632,447,118,174]。同実行source前後一致だが先の165枚診断とはsource版が違うため、同一版比較とはしない。rootはseq159の公開雷電fullfaceを元画像で視認。閾値低下/ref追加をせず、既存固有art照合の再利用を次診断に指定。chain修正だけで直ちにlivepilotへ進めず、この既知anchor不足も解消後に最終host/freezeへ進める。

### 追加境界33件通過・公開art診断のhandoff到達（2026-10-06）

own-chain-integration-v1.xmlの31件通過後、新permission境界を追加。repro-v1の16fail/10pass、v2のfrozen rule fixture setup error、v3の7failを保全。v3はfrozen Frame変更5件・planner index fixture1件・uint8 fixture1件を修正し、own-chain-boundary-v4.xmlが33pass/54.632s/0error（Implementer exit0報告、root XML確認）。closed parent、親目的/実点/client/epoch結合、merged conflicting None、新modeでの旧Main1分岐へのescape拒否、time_limit時に新取得せず最終実frame/stateと直前認識を別roleで保存する境界を対象にした。入力直前Cancelとgoal側のreceipt/caption結合は追加検証中であり、最終host/実機成功ではない。

public-anchor-art-feasibility-v1.jsonでは既知候補bboxのart照合が新159..161で成立したが、静止同Darkも一致。位置oracleを除いたpublic-anchor-oracle-free-diagnostic-v1.jsonは公開ROI全探索＋fullface投影・edge近傍支持・一意性で新165枚中seq158のみ、旧public4枚中1枚、同名静止/別CID各負例0。edge支持1.0は予測辺2px近傍にCanny edgeがある率であり、全輪郭の確定ではない。元inlineをpublic_anchor_oracle_free_diagnostic_v1.pyへ保存し再現可能にした。

新159..161/旧44..46は最終ambiguityだけで拒否。同sceneの17..29特徴点を共有するモデルの推定bbox差が3pxを超えることをpublic-anchor-scene-support-overlap-v1.jsonで測定。新閾値合わせではなく全pair共通6点以上・両ref共通spread39x36・残差2px以内を要求したpublic-anchor-common-support-existing-conditions-v1.jsonで8枚中7枚が同個体候補、新161は2.061pxでunknown維持。別candidate IDの強弱2個体syntheticは共通0で拒否したが、画素2個体検出の証明とは区別する。

新候補を原seq151から順序通り既存trackerへ接続したpublic-art-anchor-tracker-diagnostic-v1.jsonは158anchor→159で永久failure。first-failure-transition診断では初期24点/正逆24/inliers24/ratio1/scale1.056/dx-34.279が通り、dy=-8.455566が下限-8を超えることだけが原因。points0はinvalidate後clearの値。

数値下限を-9へ合わせず、入場前・他flowguard全通過・現在の一意同CID publicface・全goodpointsのface内包含・候補/flowbboxのpublicROI内を要求する段階限定案を診断。public-art-anchor-stage-up-diagnostic-v1.json/scriptで原151から29frame、158anchor→179handoffへ到達。dy例外は159の1回、元anchor/points/traceを継続し再anchor0、入場後旧guard維持。handoff7points/ratio1だがreadyfalse/current_ready_geometryなしのため入力可能・操作成功とは扱わない。後続ready/blank/Main1とstage負例をResearcherへ依頼。これらは診断コードのみ、production未実装、E2E0。
