# 限定Main1→End試作の状態（2026-10-05）

## 現在の結論

自律実機入力は未開始。実ランタイムと同じMSS専用の通常盤面・phaseメニュー校正がそれぞれ新独立3/3枚で成功した。Endバナー資料は未収録で、目的完了を確認できないため全2stepの起動はまだ拒否する。v1/v2/v3の取得元不一致も失敗として保存し、100件/3秒/99%は未達。

## 最小構成

`artifacts/phase-only-calibration/calibration.json`と`phase-route.json`は既知盤面のMain1→Endだけを対象にする。生成元は`scripts/build_phase_calibration.py`。

- 通常盤面の陽性AND: selfMain1円(window938,312,101,95)、clear_center(480,402,320,40)、clear_card_menu(268,350,12,100)。
- フェイズメニューの陽性AND: title(495,402,295,27)、Endボタン(952,491,114,120)、選択中Main1(510,494,117,119)。
- 3根拠が全て新鮮な実テンプレートと.98以上で一致した場合だけ、限定文脈を生成する。confidenceは最小値、競合はunknown。一致しなかったことからnone/idleを生成しない。
- Endバナー(449,366,403,53)は結果のphase=ENDだけの根拠。次の操作可能idleを生成しない。
- 座標はwindowからclient1280x720へx-1/y-31。生成座標だけに微小epsilonを付け、floor/ceilの境界誤差で1pxずれないようにした。ROI整数切抜きとの同一性回帰あり。全体Rect実装や認識閾値は変更していない。
- 限定監査profileはself/Main1、CHANGE_PHASE→CONFIRMの2操作、非空目的、End到達、指定prompt、カードID/素材/履歴依存条件なしに限定。全デッキ監査の既定値は維持し、34操作/54不足を解消したとは扱わない。
- logical最終stepはメニューが閉じただけでは進まず、目的状態差分まで既存50ms周期で確認を継続する。他の非logical経路は維持。カード目的は実count差分、phase目的は実phase差分を使う。

## 版と失敗

v1はtrain007/009/011/022/023。訓練画像自体で正規化切抜きの1px差を検出。独立044はphase/prompt不明で拒否し`evaluation/phase-only-recognition-v1.json`に保存。低LP盤面の明るさ・発光も訓練時と異なった。

v2は整数切抜きを修正し、Tester指定の045だけを同じROIの訓練例へ追加。044は訓練に使っていない。校正SHA256は`be737032831c29e15487b8113e03d4e7bd74a7099ed93b8b02dd4076729bd7bb`。

固定後の独立046はclear_center .99623で一致したが、selfMain1円とclear_card_menuが.98未達。入力0、phase/prompt unknown、rule_blocked。`evaluation/phase-only-holdout-v2.json`へ保存。単一テンプレートの追加で認識できたことを一般化せず、Researcherが045/046の時間変動を調査してから次方式を決める。000-028は設計資料で独立評価ではない。

## 実行準備のコマンド（認識合格前は起動しない）

実入力担当Testerが実行する。まずread-onlyのWindowsDesktopでタイトルとclient矩形を再取得し、推測座標ではなく現値を確認する。

```powershell
.venv/Scripts/python.exe -X utf8 -c "from master_duel_advisor.safety import WindowsDesktop; d=WindowsDesktop(); h=d.find('masterduel'); print({'hwnd':h,'client_rect':d.client_rect(h),'foreground':d.foreground()})"
```

旧観測値`(-1918,817,-638,1537)`と一致し、Master Duelが前面で、限定認識が独立試験を通った場合の1目的pilot例。

```powershell
.venv/Scripts/python.exe -X utf8 -m master_duel_advisor agent-loop --rect=-1918,817,-638,1537 --window-title masterduel --calibration artifacts/phase-mss-complete-calibration/calibration.json --database data/decks/thunder-dragon-review/cards.sqlite3 --plan-book artifacts/phase-only-calibration/phase-route.json --benchmark-trials artifacts/phase-only-calibration/trials.json --offline-cards --fast --max-seconds 20 --max-actions 2 --max-retries 0 --max-same-action 1 --output artifacts/phase-pilot-UNIQUE
```

最終確認後、2子操作上限で停止して追加ターン入力を行わない。入力結果不明は操作数へ数える。送信前InputBlockedは非送信で操作数へ含めないが20秒の実行期限で停止し、事前目的は失敗/中断として残る。目的完了までの時間だけが標本で、起動前の手動draw待ちは含まない。入力前のガードを回避しない。MSS初期化がDPI設定へ影響する可能性は未実測で、失敗時にinitial/current矩形から切り分ける。

## 検証

最新ソースで全252成功・4スキップ（Windows通常ユーザー、専用basetemp、`artifacts/phase-tests.xml`）。対象60成功、合成demo4/4・実認識gatefalse、compileall正常。独立画像認識の失敗は上記に残し、全単体テスト成功を実機合格と混同しない。

## 本試験の案

pilotと本試験は分離し、code/config/ROI hashを固定した同一版のcohortで比較する。100目的案は効果20、特殊召喚25、通常召喚15、魔法罠20（発動16/set4）、攻撃10（対象5/直接5）、フェイズ10（Battle5/End5）。失敗試行を交換しない。目的途中に人またはComputer Useの補助を入れた試行は自律成功から除外する。phase-onlyの速い子操作を100回数える評価は禁止。


## v3時間変動特徴（固定後）

Researcherはv2失敗について位置ではなく発光の時間変動と実測。訓練連番047〜066から64x32 RGB特徴の画素中央値prototypeを作り、全20フレームの最大平均RGB偏差が.01以内の画素だけを使うstable_rgbを追加した。circleは589画素、clear_card_menuをwindow(268,250,12,40)へ変更して580画素。clear_centerは従来RGBを維持。action.phase_openと文脈円は同一prototype/maskであり、独立した証拠2票として数えない。

scoreの分母はmask内の有効画素数×3だけ。mask外のゼロ埋めで一致率を水増ししない。訓練はlabelごと10枚以上、安定画素256以上が必須、不足時は明示エラー。既存のlabel間marginは維持し、認識閾値.98は下げない。prototype/maskの計算は初期化時だけ。

v3校正hash: 7b9c7773ec978aca9ae3d44544997fde35b5d51c3603f8b3bce94677769f7c06。参照PNG、prototype、maskのSHAはasset-manifest-v3.jsonとrun-metadataにも保存する。元v2hashと失敗レポートは上記のまま維持。

ROI/feature凍結後の新独立067はMAIN1/none .994897、phase_open .996934で認識できた。API0、画像取得を含まない認識約1.10msは単一画像の処理時間でありE2Eではない。evaluation/phase-only-holdout-v3.jsonに保存。

ただし通常権限MSSの実client画像は円が拒否、clear_center .98848、左境界 .98516。制限環境MSSは全画素黒を確認し全候補拒否。画像内容があることと固定認識が通ることを分けて確認中。evaluation/phase-only-capture-source-v3.jsonに両方を保存。黒画像を高速処理した値は成功E2Eに含めない。

最新v3は全257成功・4スキップ、対象65成功、compileall正常。artifacts/phase-v3-tests.xmlとevaluation/phase-v3-validation.jsonに記録。認識独立1画像の合格を全面対応・自律操作の合格へ昇格しない。


## MSS専用v4の部分校正

前面MSSでもSky訓練の円が拒否した。Researcherの±2px比較は全ROIで(0,0)が最良で、座標のずれを支持しなかった。閾値を下げず、実ランタイムのMSS sourceへ訓練を揃えた。

`build_phase_mss_calibration.py`はclient1280x720を直接cropし、タイトルバーを二度除去しない。通常盤面はMSS_TRAIN_v4の40枚だけを使い、Skyの画像は混ぜない。feature/ROI/閾値はv3と同じ。circle923・左境界912安定画素。訓練40/40の最小AND .997608。固定後のMSS_HOLDOUT_v4は前後foreground/rect一致の3枚で、AND .998101/.997863/.998623、通常phase認識と候補が成功。取得なしの認識1.20〜1.50msはE2Eではない。

通常版: `artifacts/phase-mss-calibration/calibration.json`、hash `2e2f38f6e7e1da069806f24e154edb338e4376390212ee47fe7891b0fe94898d`。メニュー/バナーを持たず全phaseルートには不足5項目。

次のMSSメニュー訓練20枚を別出力へ追加。title/End/selectedMain1/action_endすべてMSS sourceだけ。固定後の前面新独立MSS_MENU_HOLDOUT_v4_foregroundは3/3成功、phase.select .999237/.999305/.999344。旧MSS_MENU_HOLDOUT_v4の非前面0/3取得は不適合取得として保持し、目的試行の失敗除外と混同しない。

メニュー追加版: `artifacts/phase-mss-menu-calibration/calibration.json`、hash `cefdee498ceb9dba3494db0d9d9118ad6fbfa8207edfd3dc46285ae5d667364c`。Endバナーは未収録。起動監査にlogical目標phase=ENDも必須とする回帰を追加し、1不足として開始拒否する。

監査修正後の最新ソースは全258成功・4スキップ。`artifacts/phase-mss-tests.xml`。source SHA256 `a6f0f7ffe6b8960a08a7c5000b3fb785f231e6252e6d4dcd0bfcebd2f13aa619`。入力0・目的標本0。独立画像の限定成功を自律成功へ換算しない。


## MSS End資料と限定完全版（2026-10-06）

Testerの受動収集444枚から、完全END PHASEとTurn5 Endを目視確認した0441/0443だけをMSS_END_LABELED_v4へコピーした。クリック補助で収集した訓練資料で、自律標本ではない。メニュー押下前0434、閉鎖中0438、途中文字0440をEnd負例/過渡として保持。全444枚をEndラベルへ転用していない。

限定完全版は `artifacts/phase-mss-complete-calibration/calibration.json`、SHA256 `170497ece4845f8b9ce69999eaba6e465016471745329f4d41d798c3ac1631dc`。訓練2枚はEND一致1.0、0434はMAIN1/phase.select、0438/0440と黒画像はunknown。既存MSS正常3枚とメニュー3枚は認識維持。`evaluation/phase-mss-complete-v4.json`へPNG/特徴のhashと結果を保存した。

phase_transition限定2操作の構造監査は不足0。これは独立End画像検証や実機成功を意味しない。独立End陽性0、自律目的0。新対戦Main1のMSS独立認識を確認してから、通常ユーザー権限で1目的pilotを実行する。初回End結果は保存画像をTesterが独立目視レビューする。全34stepルートの不足54は維持。エンジン変更はなく、上記258成功/4skipとソースhashを維持。

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

Researcherレビューで、正配置後の別card選択を見落とす早期returnを修正。全履歴で最後の有効選択と対応配置だけを採用する回帰を追加し、最終全278成功4skip。


## 通常召喚の限定3操作版（2026-10-06）

MSSの適合済みinitial/menu/placement/post各20枚から、同位置の増殖するG（CID9455、ATK500/DEF200）を中央monster_2へ通常召喚する限定校正を生成した。600という途中目視値は誤りで採用しない。資料収集は補助操作で、通常召喚の自律目的標本は0。

`artifacts/normal-maxxc-calibration-v1` にcalibration.json、normal-route.json、trials.json、training-manifest.json。校正hash `eab254044b68585b0d0d3ad1881023f1873c412aeb127db2f8016657f26d851b`、routehash `7c178bb4922e069c3e16dbca800d98cb2ef387f4d7036edb0e7ae67dd729b7f2`。全ROIはclient座標。hand_layoutは局所slot輪郭(409,615,22,105)で、他4枚の内容や汎用手札枚数5を推定しない。対象カード画像と通常盤面の陽性ANDが揃う場合だけ候補になる。

normal_summon監査はSELECT_CARD→NORMAL_SUMMON→CONFIRMの3操作に限定。宣言CID、self/Main1、同目的/同zone、follows、期待prompt、配置source/target、実選択/召喚有効/局所手札文脈を検証する。turn不明を補完せず、通常召喚使用履歴も固定しない。目的の占有empty/occupiedとfieldCID画像まで揃わないと監査を通さない。全デッキの54不足はそのまま。

訓練80枚では初期none、menu card.menu、placement placement.select、post occupied+field9455を確認した。postのprompt/phaseはunknownであり、都合よくidleを固定しない。_verifyは最終logical目的の全肯定証拠＋画像変化＋新sequence＋planner期待が揃えば、直前unknown→結果knownでも目的成立を確認できる。未送信/送信不明、同画像、planner拒否は成功にならない。既存非logical経路とphase確認の回帰も維持。

旧Sky000〜071の72探索負例で開始誤許可0、ただし独立評価ではない。新postと別対戦同位置Maxxの独立holdoutが必要。全304成功4skip、対象97成功、compileall正常。sourcehash `0f6ef470e7a0395c9672b961a63b21c1a8098fc859cf223b85726bd44980d1e4`。前zonegoal sourceは `artifacts/normal-zone-goal-source-7e64d110.zip` に保存。normal-profile-validation.json/normal-maxxc-training-v1.json/normal-maxxc-old-negatives-v1.jsonへ証拠を保存した。
