# 限定Ash通常召喚と実配置先inspect

現在のデッキ・ソロモードで、既知のAshメニューから開始する別profileです。旧normal_summon/LogicalZoneTransitionのfieldCID条件は変更しません。

通常召喚UI→中央monster_2配置→その実zoneのinspectの3入力を1目的として記録します。最終CIDをself.zonesへコピーせず、明示panel無し→指定zone内の実入力→新sequenceにAsh詳細出現の遷移で対応を確認します。fieldハイライト差は実資料で未確認のため使用しません。

開始条件はnative BGR1280x720のMSS、同一client矩形、self/Main1/active/idle、Ash詳細CID12950、検出した有効normal menuと相対手札選択輪郭、中央zone emptyです。Turn番号・手札枚数・LP・中央以外の自場の空を必須にしません。固定menu探索はorigin x316..444/y473..521、74x79の証拠crop、score>=.98/位置margin>=.03。Special/Flip/無効種類は未検証で、この限定Ashの実表示normalのみ対象です。SETは別操作。未知中間表示・panel残留・overlay・配置先不明は停止します。

目的確認は開始のCID/hand/normal/empty、実NORMAL_SUMMONと実配置、同client・新sequence・鮮度、zone occupied、明示panel blank、zone内inspectのinput_sent=true、入力活動token整合、新AshCID+occupied+field.inspectを全て必要とします。未知名はblankではありません。各stepの型・CID・target・実送信点も確認します。再試行0、最大3入力。失敗時も登録目的分母に残します。

既存WindowsDesktopはmouse_eventを使用します。input_sent=trueはbackend呼出完了の記録で、OSへの送信イベント数やゲーム受理の証明ではありません。成功は上記visual goal・入力活動監視・独立レビューで別途判定し、画面結果がない呼出しを成功に数えません。

MSS取得由来をFrameへ明示し、saved_image/video/unclassifiedをclient矩形やnow風時刻だけでliveへ昇格しません。保存画像はoffline0での認識診断だけ。monotonicは鮮度、perf_counterは処理時間で、異なる時計domainを減算しません。

[GetLastInputInfo](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getlastinputinfo)のtokenは同Windows sessionの粗い活動検出として不透明値の一致のみ確認します。同tick等の見逃しがあり、全外部入力不在の完全証明ではありません。API失敗/変化は新profileで安全停止します。独立Testerは実送信点と前後画面をレビューします。既存backend/他profileの入力ガードは維持します。

校正builderは補助資料ASH_NORMAL_INSPECT_TRAIN_v1_20261006の4stage各10枚のみ使用。assisted skyの成功応答はruntime送信済fixtureへ変換しません。独立A1 Ash3枚は訓練流用無し。post-transition104枚は配置前captureの計測手順失敗として除外し、ゲーム待ち時間にも使用しません。40/40は訓練一致・入力0/E2E0で、実機成功率ではありません。

## 固定後の手順

advisorをcwdとして、Testerが現在のclient矩形と完全window titleを確認して新processで実行します。新規outputを指定してください。RECTは実値へ置換します。

```powershell
.venv/Scripts/python.exe -X utf8 scripts/preflight_normal_inspect.py --rect RECT --window-title masterduel --output artifacts/baseline-tester/ASH_INSPECT_PREFLIGHT_v1
```

preflightは新MSSを認識し、点の範囲/前面/epochを確認して画像と候補を保存するだけで、入力0です。独立目視でnormal円内部、Ash、selfMain1、中央emptyを確認してから、同deckSoloを試験条件に記録した事前登録pilotを行います。

```powershell
.venv/Scripts/python.exe -X utf8 -m master_duel_advisor agent-loop --rect RECT --window-title masterduel --calibration artifacts/ash-normal-inspect-calibration-v1/calibration.json --database data/decks/thunder-dragon-review/cards.sqlite3 --plan-book artifacts/ash-normal-inspect-calibration-v1/normal-route.json --benchmark-trials artifacts/ash-normal-inspect-calibration-v1/trials.json --execution-context artifacts/baseline-tester/EXECUTION_CONTEXT_CURRENT_DECK_SOLO.json --offline-cards --run-purpose pilot --fps 30 --max-actions 3 --max-seconds 15 --max-retries 0 --max-same-action 1 --settle-seconds 0 --verify-poll-seconds 0.05 --output artifacts/baseline-tester/ASH_INSPECT_PILOT_v1
```

pilotはpreflight保存画像を使わず、独自新MSSと各step guardで動作します。1pilot成功でも100代表Actionの達成と扱いません。現版の未分類/verify残差は演出・通信の直接実測ではなく、既存計測仕様の制約を維持します。速度最適化は未実施です。

## 検証と固定版

40train認識一致、独立失敗境界と実pipeline/planner接続を含む新unit60成功。既存normal/telemetry/loop併用153成功。sandbox全回帰431成功/9失敗/4skip（9件は既存DPAPI credential_protection_failed）、通常ユーザー環境で440成功/4skip43.74秒。追加の結果確認鮮度ガード後も通常環境で全回帰を実行し、evaluation/inspect-host-tests-v2.xmlを最終結果とします。compileall成功、demo4/4で実機gatefalse。lint/type checkerは未導入のため未実行。

evaluation/normal-inspect-fixed-v1.jsonに固定source/校正/route/helper/tests/全recognition assethashを保存しました。source0192ffc2ac4d7d787a5ad6eb04412a7774d21fe73cc68918383ed3103afd9e76、校正fbb11ef8453142247a957dd3dedb61efe50acd2745dc290a481d6a6b633e72b6、route2caacbd58fb731bcea385bba491aa050bf142b642c20f395e17280f00ef5c217、components f174d1c8962fec995a145ee05538594d483927c68abb08d5e321617ab8f6b1d6。旧A1の設定/moduleは固定維持し、A2source変更を別fingerprintとして記録します。DB/本試験fingerprintの旧資料とは混在できません。

## v2追加layoutと診断

v1の新Turn2/左端Ash/手札6のpreflightは入力0で安全棄却しました。normal最大score.976373、位置margin.183008、中央empty.978574、固定手札輪郭.854690。局所256点診断でも同最大で探索取りこぼしではありません。失敗画像は訓練に使用せず、診断JSONと実機receiptを保存しました。

別pathの新menu訓練10枚で、既存stable_rgbの参照を追加しました。旧v1/A1資産は不変。v2は左menuを対象とし、既存placement/post30枚を保持します。normalの実crop(338,502,74,79)を公称探索anchor(380,497,74,79)へ正規化、手札輪郭の実crop(365,584,18,112)も同じ平行移動で結合します。有限探索I/Fの機械名solar-menu-v2を使用しますが、A2専用detector.json/hashが新Ash参照を明示し、Solarカード認識を意味しません。score.98/位置margin.03/安定画素最低256は維持しました。

40train一致、旧v1/新v2/A1関連92test成功9.62秒、compileall成功。source0192ffc2...は不変、calf7b80fb3716a13eac239e69fa286d9ddf3464e6ddfd35aa98a5a565be83a946c、detector d23fe218af54afc642b04e792ab8cb7d548cadd030c938a9470e60a0866fe6e4、components b1922de40076fec02ccdf34d51e15f233b226ac8e8085843a97af61d8976e4cd。evaluation/normal-inspect-fixed-v2.jsonに固定記録。固定後新MSSは同一sceneの時間的再取得で、別場面汎化の証明ではありません。

v2 preflightでは上記commandに `--profile-base artifacts/ash-normal-inspect-calibration-v2` を追加し新規outputを指定します。pilotはcalibration/plan-book/benchmark-trialsのbaseをv2へ置換します。最新全回帰は444成功/4skip45.45秒（evaluation/inspect-layout2-host-tests-v1.xml）。実機pilotにpytest負荷を混ぜず、終了後に開始します。

固定後新MSS preflight_v2は入力0/E2E0で通過しました。normal.993930/位置margin.192536/hand_selected.994110/empty.995695/detailCID.999391、候補点client(375,542)は独立目視で召喚円内部。同client/前面/epoch一致、source/components固定一致。これは同sceneの開始認識と点レビューで、正常召喚の結果確認や実機E2E成功を意味しません。

## v2実機pilotとv3固定mask

登録1目的のv2pilotは2入力後verification_failed、3599.910msで成功0/retry0/fallback0。正常召喚→配置UIは確認しましたが、実配置後occupiedが未知となりinspect未実行でした。内部処理1461.198ms（認識累計905.281/capture累計526.216）、verifywall3270.678ms、残差1942.127ms、未分類196.584ms。認識28回のp5031.837/p9537.929msで、905msは1回の認識ではありません。認識不成立による反復が主な阻害条件で、高速化はまだ行いません。残差は純ゲーム待機ではありません。

当時のverify最終画像は欠測。停止後別MSSは時刻・出所を保った別診断資料で、当時へ代用しません。停止後occupied RGB.941843/inspect.931586、blank.992559は陽性、occupied未知でpromptを構築できませんでした。±4pxの81位置では同位置が最大でした。旧postの中央cursor/blue表示と停止後白表示の差はありますが、原因をhoverと断定しません。

read-only比較のgray相関は旧occupied最小.993602/empty最大.123019/停止後.784347、RGBより表示差が消えるとは実証できず、別尺度の閾値を流用しません。既存RGBの単一条件descriptor rows6..24除外で、停止後occupied.980458/inspect.980658、旧occupied最小.998293、空zone負例最大.778586/配置UI負例最大.789297。方式選択に使った既知診断で、独立holdoutではありません。

Coordinator承認でv3の専用2regionにそのmaskだけ接続。occupied1933→778/empty674→330/inspect1994→778有効画素、score.98/margin.03/最低256保持。設定・mask/prototype hashをfield-mask-provenance.jsonへ保存。Ash12950中央field表示限定で、汎用occupied/CIDへ一般化しません。旧A1/v1/v2/他featureにmaskを適用しません。

v3ではtimeout時に最後の実取得frame/hash/seq/原clock/stateを保存し、認識未完のstateはNoneと明示、前のlast_recognized frame/stateも別保存します。期待facts/prompts/rawscoreを失敗時のsidecarへ記録し、rawscoreをconfidenceへ昇格しません。failure_diagnostic spanで失敗保存の内部時間を分離し、成功hotpathに追加の同期I/Oはありません。

v3固定UTC2026-10-05T19:09:26.721958+00:00、source870c0c2ddadb489603ae21fc8b27bd2ac2b53442e99e2b766c387d382704fc48、cal89c908a67a8e77fa7eb8a21fcd245cec7dfc778b953ba0933a8de312a0aaad37、components e0fa92f14d91465a51deda4785aaf757fd4338b49d00d672cace99f994b20efb。evaluation/normal-inspect-fixed-v3.jsonにhelperも含め固定しました。対象103test成功14.88秒、最終全回帰455成功/4skip51.02秒（inspect-mask-host-tests-v1.xml）、compileall成功。ruff/mypy/pyright未導入でlint/typecheck未実行。

現在postの固定後新MSS10枚をまず入力0で採取し、`scripts/evaluate_inspect_post.py --manifest NEW_MANIFEST --fixed evaluation/normal-inspect-fixed-v3.json --profile-base artifacts/ash-normal-inspect-calibration-v3 --output evaluation/ash-post-temporal-v3.json`で認識のみ評価します。元MSS由来/monotonic/実sequence/UTC/hashと、保存画像再認識offline0を分離。期待selfMain1/idle/active/promptnone/occupied/明示blank/detailCID未知/inspect候補、実前提履歴が無いplannerblockedは別に記録します。同scene時間的評価の通過後、全回帰終了を待って新対戦1pilotへ進み、以前の失敗目的を成功へ再開・換算しません。

固定後新post10枚は10/10認識一致、occupied最小.980459/detail_blank最小.989980、入力0/E2E0で目視と整合。履歴無しplannerblockedを保持しました。同scene時間的確認で、独立対戦の目的成功率・速度とは区別します。固定版を維持して次の新対戦pilotへ進みます。

## v4既存UI参照の併用

新対戦のTurn1/手札5/左端Ash開始はv3 freshpreflightで安全棄却し、入力0/pilot0でした。Main1/CID/中央emptyは陽性でしたが、normal最大score.968336/位置margin.198019、hand_selected未知。最大bbox[380,497,74,79]は既存探索内で、範囲漏れではありません。未変更旧v1参照では同画像normal.993430/margin.233907、v3手札輪郭は相対座標固定.978796→(+1,-1)で.980392。v2で旧表示参照を置換したcoverage不足と小さな輪郭位置差が測定根拠です。

v4 UiEvidenceBankは既存v1/v3の同義NORMAL参照を位置ごとmaxに統合し、異なる位置の候補に対してtop1-top2を判定します。同じボタンの同義参照を競合へ数えず、別位置の2候補は曖昧として棄却する境界testを追加しました。画像fingerprintは各探索位置で1回作り、既存2prototypeを比較します。A1 module/config、v3 asset/profile、旧normalの条件は変更しません。

手札は同ボタンcrop原点からoffset(27,82)にある18x112輪郭だけを、固定半径3pxで既存2表示参照と照合します。範囲は既存detectorの3px精探索、旧/新crop相対offsetの一致、今回1px偏差と既知負例比較によります。手札枚数別・今回画像の新テンプレートは追加しません。輪郭は選択表示でありCID/zone/入力座標を生成しません。score.98/margin.03/最低256、Ash中央normal inspect限定、既存detail/blank/実receipt/epoch/freshness条件を維持します。Special/Flip/disabledは未検証です。

方式選択資料64枚ではAsh開始26枚のbutton＋hand採用26、非menu37枚のbutton採用0。有効Solar menu1枚はnormal UI検出しましたがAsh輪郭不一致で、CIDguardも別です。これは既知画像比較で、独立holdout/実機E2E成功ではありません。evaluation/normal-inspect-prototype-bank-diagnostic-v3.jsonに元hashと各scoreを保存しました。

microbench20回は旧button平均33.941ms、bank47.344ms（追加13.403ms）、bank手札4.851ms。既知保存画像offline0の局所認識コストで、速度改善・実機E2Eとは扱いません。scripts/benchmark_inspect_ui_bank.pyで再計測できます。新実機評価にpytest負荷を混ぜません。

対象116pass、追加scope境界1pass。追加test初回のfrozen Region直接変更fixture1失敗はmodel_copyへ修正し解消。通常ユーザー全回帰初回は268pass/4skip/201setup error、201件すべて共通Temp/pytest-of-userのACL拒否でXMLを保全。未作成のworkspace内basetempを指定した全suite再実行は469pass/4skip58.08秒（evaluation/inspect-ui-bank-host-tests-v2.xml）。pytest cache書込ACLの警告1件は結果に影響しません。compileall成功、ruff/mypy/pyright未導入でlint/typecheck未実行。以降の全suiteは新規workspace basetempを明示します。

固定UTC2026-10-05T19:32:00.570833+00:00、source601210b4d6176248c5b50b978d42ee02a161977fc3a6744f09434d314d89fa54、cal369b9ce8d38fffba9a5dbb2b12541c9185c47f29b078e5c6df1817e807aea9f2、components068ad2473e6d767283134acb3f75130dca466253b46681dbf94f594aa99a14a5。bank/config/手札asset/半径設定/helperもevaluation/normal-inspect-fixed-v4.jsonへ固定しました。

現在の未入力開始画面から固定後新MSS10枚を採取し、`scripts/evaluate_inspect_menu.py --manifest NEW_MANIFEST --fixed evaluation/normal-inspect-fixed-v4.json --profile-base artifacts/ash-normal-inspect-calibration-v4 --output evaluation/ash-menu-temporal-v4.json`で評価します。元mono/seq/UTC/rect/hashを保ち、再認識はoffline0/proof無し/input0/E2E0。期待selfMain1/card.menu/idleactive/detail12950/handselected/enabled/中央empty。同scene時間的再取得として扱い、通過後はv4baseのfreshpreflightで開始・点を別確認してnew1pilotへ進みます。旧失敗目的の再開・成功換算はありません。

## v5手札の形状証拠

v4固定後新menu10枚はeligible10/input0/pilot0、開始認識3/10で停止しました。Normalは10/10score.99434..99578、Main1/empty/CIDも通過しましたが、hand RGBは.987792から.958246へ低下。ボタンbboxは全て380/497/74/79、手札探索半径3→12でも失敗画像の最大scoreは改善せず、範囲漏れではありません。局所特徴の10枚間RGB range平均.1280/max.4484で時間変動があり、静的発光帯テンプレートを追加し続ける方式を棄却しました。元画像を追加訓練へ転用せず、方法選択資料として保全しています。

v5だけhand_selectedの必須RGB判定を置換。Canny50/150、HoughP(rho1/theta1度/threshold40/minLength65/maxGap8)を、Normal検出crop相対x+20..155/y+70..220の手札ROIへ適用します。幅80..120px/重なり65px以上のほぼ垂直2辺（axis許容3px）と、手札せり上がり高さの上辺をANDし、同じ左右辺との交差を拘束します。発光で分断したHough端点は、実Canny edgeのaxis±3px/連続欠落8px以内の支持で補います。長い線分が角を越えて続く場合も、Hough端点を角と同一視せず、左右線への交差で判定。交差から下へ65px以上の手札矩形が必要です。許容幅を画像ごとに広げません。

単純3辺存在の診断は30/30でしたが、初期端点接続の実装では実画像を拒否しました。端点と角が一致するという誤った拘束を上記実edge交差へ修正しました。失敗XMLは保持。最後のSolar対比test期待CID9455誤記は実registry13581へ修正し、Ashcandidate無しという本来の境界を確認しています。

形状陽性のconfidence1は固定predicateを満たしたbinary値であり、学習確率・CID精度・一般識別成功率ではありません。sourceはgeometryの固定parameter hash、CIDは詳細registry、Normal種類は固定UI bank、空zone/現在context/clock/入力receipt/blank遷移は従来ANDで独立検証します。RGB raw scoreはconfidence0のhand_source_diagnostic factへ保存し、合法手の根拠へ昇格しません。v4と旧profileのRGB分岐は維持しました。

既知対比65枚はAsh選択30枚が候補陽性、配置10/非選択post10/fieldinspect10/相手turn選択3/他hover1のAsh候補0。別CIDのNormal menu1は形状陽性でもCID13581でAsh候補0でした。相手turnの選択手札＋詳細だけではNormalbuttonが無く、合法手へ接続しません。fieldinspectは手札outline残留の対比で、field action menuそのものではありません。Special/Flip/disabled Normalの確実資料は無く、未検証のままです。これらは方法選択に使用した既知画像で、独立holdout/実機E2E成功ではありません。

対象134pass26.64秒、通常ユーザー全回帰486pass/4skip66.63秒（evaluation/inspect-hand-geometry-host-tests-v1.xml）、compileall成功、lint/type checker未導入。新規workspace basetempとcacheprovider無効で既知ACLを回避しました。microbench20回は旧button平均35.604ms/bank48.246ms、手札7.335ms（RGB診断＋形状）。以前のv4benchとは使用画像が違うため、その差を性能改善/悪化へ換算しません。実機E2Eと別です。

固定UTC2026-10-05T19:52:22.847196+00:00/sourceea92677c811e34bc17a000a0dcb0b55febac11e024a17deb2e32942e9ffa30fe/calf59a2c018516d809f63e8e30620aece6e177c7736696d5452b33d60625b99672/components2e2713fa0800e78e809f15b7f1116311f2e5876878149d2e020d101eb95aa616。evaluation/normal-inspect-fixed-v5.jsonに固定。

新MSS10枚を取得後、`scripts/evaluate_inspect_menu.py --manifest NEW_MANIFEST --fixed evaluation/normal-inspect-fixed-v5.json --profile-base artifacts/ash-normal-inspect-calibration-v5 --output evaluation/ash-menu-temporal-v5.json`で同scene時間的確認。元取得clock/seq/UTC/hash/rectと保存画像offline0を分離します。通過時は同v5baseのfreshpreflight→新1pilot。成功は3実入力と最終field詳細CIDの視覚goal/独立点レビューを満たしたときに数え、100代表目標は未達です。


v5固定後の新menu10/10・freshpreflightを経て、登録した実機正常召喚1目的が成功。NORMAL→配置→実zoneinspectの3入力、中央Ashと新詳細CIDを独立レビューしました。E2E2334.8561ms、内部1091.9664ms(capture304.6878/recognition756.5008の反復累計)、verify wall2036.7887/residual1055.7850/未分類187.1047ms。retry/fallback0、3点誤clickレビュー0。residualを純粋なゲーム/通信待機とは呼びません。rawcal SHA f59a...とrun metadata正規化cal3133a977...は異なる定義で、value_hash(parsedcal)の一致をevaluation/normal-inspect-pilot-calibration-integrity-v5.jsonに確認。実機成功1件で100代表/99%達成を主張しません。artifacts/baseline-tester/ASH_INSPECT_PILOT_v5_20261006/tester-review.json。
