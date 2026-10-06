# Solo限定の通常召喚・フェイズ・意味別応答辞退

現在デッキ・Solo試験の任意発動辞退を、既存Action/RulePlanner/UiPolicy/AgentLoopへ接続しました。候補カードCIDはunknownのままです。戦略最善や隠れた発動結果は推定しません。

2つの応答を混同しません。

- 相手の召喚成功応答: 元の召喚全文＋赤Main1＋有効Cancelから、実Cancel後の新sequenceで次の終了全文＋赤Endへ進むことを確認。取得したafter10枚は次End応答であり、modalなしMain1資料は欠測です。完了型は`opponent_end_response`、modal_absentを捏造しません。
- 相手の終了応答: 元の終了全文＋赤End＋有効Cancelから、実Cancel後の新sequenceでmodal_absent陽性＋青selfDraw表示を確認。after20枚はDraw演出中です。ドロー解決・idle・TURN表示には数えず、次入力のidle条件は維持します。

strict条件で絞った候補と意味別UiPolicyの両方が必要です。期限切れ強制選択でも迂回しません。未知の儀式・効果・攻撃応答は候補を出しません。`solo_basic_operations`は通常召喚3操作・phase2操作・意味別辞退各1操作を目的ごとに旧専用validatorで検査し、宣言順序に依存せず、別目的pending中の割込みを拒否します。

新scopeの入力は実MSS由来・元monotonic/sequence・同client・前面・鮮度・入力epoch・固定assetを必要とします。保存画像へ現在時刻を付けてliveへ昇格しません。新goalは実Cancelのbackend呼出完了、実点が校正領域内、取得epoch/送信後epoch検査、取得sequence、陽性の前後UIをANDで確認します。`input_sent=True`は既存backendの呼出完了でありOS送信件数/ゲーム受理の証明ではありません。GetLastInputInfoは粗い活動tokenで、全外部入力不在の完全証明ではありません。実点と画面結果はTesterが独立レビューします。

訓練収集82枚の分類結果は召喚before10、終了before10＋召喚after次End10、終了afterDraw20、未知chain/ritual/effect/attack32。前3種は想定通り認識し、未知32は候補0件です。旧normal40枚の意味・detail/hand/button/occupancyも同じ結果でした。訓練/方式選択資料であり、独立holdoutやE2E成功標本ではありません。

Cancelのhover黄色縁と非hover白縁を20枚のstable_rgbへ混ぜた初版は、安定画素70<256で起動拒否。初版assetを保存しました。2button領域だけ既存RGB同義参照の最大scoreへ変更し、178×40原画素=7120、64×32 descriptor=2048全画素×RGBを使用します。maskでminimumを迂回せず、threshold .98/margin .03を維持。全文・phrase・badgeは独立stable_rgb AND。無効Cancelの実資料は未確認で、ボタンのみの一般識別を主張しません。

初回対象回帰は196pass/16fail。うち10件は起動時guard boolean snapshotによる旧inspectの保存画像/鮮度/hash拒否漏れで、dynamic propertyへ修正しました。残り5件は新after fixture指定漏れ、1件は共通book2semantic必須validatorです。失敗XMLは保持。最終対象230pass21.08秒、通常ユーザー全回帰549pass/4skip79.35秒、compileall成功。ruff/mypy/pyright未導入でlint/型検査は未実行です。

計装はverify親spanとpoll_wait/frontmost_stop_check/verify_input_control/predicateの子span、artifact_write/log_write/pre_input_control/post_input_controlを記録します。内部処理はverifyとpoll_waitを除いた区間union。親子の単純和で重複加算しません。`poll_wait_ms`は別集計、`verification_unmeasured_ms`はverify残差からpoll待機を除いた値で、通信/演出の直接測定ではありません。旧名`game_wait_estimate_ms`も残差の互換名です。途中失敗・逆順・空区間・親子重複を合成テストしました。

固定は`evaluation/solo-basic-fixed-v1.json`、UTC2026-10-05T20:28:11.052070+00:00。source `f71d56399fac2f40d813ec4426d800f961720c9214c59b4ab64275900236992d`、rawcal `d1fa9b4aa54a0dced7fca49b69d11b8bc4a05ca383ead7acbc97335e5b96f983`、components `dac03935c08d6203d7cfcb97090496b312e115e4e97bbfeea2c24da39bfc7713`。baseは`artifacts/solo-basic-calibration-v2`、book `solo-route.json`、UIpolicy `ui-rules.json`、End予定1目的は`end-trials.json`。旧v5資産・測定標本は保持し、新版cohortへ混ぜません。

固定後に保持中Endを新MSS10枚で取得し、`scripts/evaluate_solo_response.py`で元時計/UTC/hashを保持したoffline0評価を行います。通過後`scripts/preflight_solo_response.py`で実新MSSの前面/epoch/点を入力なしで確認し、独立点レビュー後、別の新取得から最大1Cancel/再試行0/10秒の登録pilotへ進みます。新scopeの実機E2Eはこの固定時点で0件、100代表目標は未達です。

## Cancel caption方式への更新と資料事故（共通固定v2）

前版固定後のEnd新MSS10枚は0/10。全文・phrase・赤Endは通過しましたが、ボタン全面RGBが.933805〜.943488で拒否されました。位置±3px探索に改善がなく、単純な文字RGB切出しも不成立だったため、RGB参照追加を繰り返さずnative文字形状へ変更しました。この10枚は方式選択資料となり、次版の独立評価には数えません。

診断の出力変数と画像ループ変数の衝突で、元訓練`end-response-before/frame-0009.png`をJSONで上書きしました。元フル画像は復元不能、原manifest整合性はfalseで、無傷81枚・欠測1枚です。事故報告は`evaluation/solo-cancel-training-input-incident-v1.json`。旧82枚分類と旧全回帰結果は事故前の記録として保持し、現在82枚を再現できるとは主張しません。事故前にコピーした固定派生button crop20枚と運用資産は独立hash監査で無傷でした。新builderは派生資産と事故リンクを明示し、元画像を置換しません。診断書込は先に新規evaluation配下へresolveし、全入力との重複と既存出力を拒否するテストを追加しました。

新経路は1280×720 clientに限定し、caption bbox `[506,674,78,14]`、button bbox `[456,661,178,40]`、点 `[545,681]`を固定しています。BGRからR/G≥160、B≤100の黄色文字を取り出し、派生20crop多数決の219画素prototypeとnative1px許容のrecall/precision最小値を照合します。.85は新しい形状尺度の方法選択条件です。旧RGB全文・phrase・phaseの.98/.03条件は維持しています。confidence1はpredicate通過であり、確率・CID精度ではありません。黄色は有効表示のproxyで、実disabled資料はなく未検証です。

無傷81枚と既知新10枚ではCancel captionを照合し、未知chain/attack32はcaptionが陽性でもsemantic ANDで候補0。Draw20・旧normal40・他の効果文字は負例、反転・4px shiftは合成負例と分けています。実送信点、caption bboxとbutton bbox、config SHA、新sequence、実前後陽性条件をgoalでも再検査します。legacy経路と資産は保持しています。

対象223pass38.55秒、最終glyph境界20pass12.77秒、通常ユーザー全回帰569pass/4skip92.41秒、compileall成功。ruff/mypy/pyright未導入でlint/型検査は未実行。全回帰XMLは`evaluation/cancel-caption-host-v1.xml`です。

固定`evaluation/solo-basic-fixed-v2.json`、UTC2026-10-05T20:53:18.723089+00:00、base `artifacts/solo-basic-calibration-v3`。source `8a61a55cc99c223d5c36a78980d7ee8b7c043cd181afeca41cf02e94c4471d14`、components `85150a68aeed81a4c5d31ee25147675d76228f83d59befdf5d1a42b6bf5d3eea`、caption config `fbb8780508c71410efaca2d36ebc64a03d184e1933ea969d29342de8cc6857f4`。rawcal/route/UIpolicyは前版と同値です。source・assets・helperを固定し、Testerへ新MSS10→freshpreflight→最大1End辞退pilotを通知しました。新版の実機成功は固定時点で0、速度改善・100代表達成は未主張です。

## 実Draw帯の確認と共通固定v3

End v2実機pilotは1Cancel後にverification_failed、elapsed3477.944ms、成功E2Eはnull。独立点レビューではCancelは適正で受理され、最後の実runtime seq19/20は青Turn2Draw＋大DRAW PHASE帯、modalなしでした。停止後Main1画像をendpointへ代用していません。seq19のmodal_absent .983859は通過、self_draw .745709だけ不成立。旧Draw ROI `[946,320,86,26]`はTurn数字上段を既に外しており、数字差だけに原因を帰属できません。訓練20は帯なしDrawcard演出、runtime帯が旧ROI全体を覆う表示coverage不足でした。診断は`evaluation/solo-end-pilot-readonly-diagnostic-v2.json`。

runtime predicate19回536.675ms/p50 27.6285ms。保存実画像pairの20回再生ではgoal判定平均.106ms、全画面changed29.555ms、generic expected33.048ms。predicate内のasset hash読取はありません。意味別辞退のgoal不成立だけpendingへ直接戻し、全画面fallbackを閉じました。generic/旧normalは従来分岐、typedの成功条件・タイムアウト・最後の実取得証跡は維持。これらは再生microbenchであり、実機改善量ではありません。

同失敗runの内部union2376.208ms、verify wall3205.613ms、verify残差1013.446ms、poll1006.973ms、verify未計測6.473ms、その他未分類88.291ms。親verifyと内部を単純和にしません。失敗証跡artifact_write186.293msも内部に含みます。残差や未計測を純ゲーム/通信待ちとは呼びません。

旧帯なしDraw陽性に加え、native `[416,337,455,51]` の白DRAW PHASE形状を1px許容・score .90で照合し、帯の上の `[970,294,32,18]` にB-R≥40/B-G≥10の青画素割合≥.15、既存modal_absent陽性をANDします。青は自己側表示proxyで、数字OCR・勝敗・idleは生成しません。形状prototype13903画素は失敗seq19派生crop、seq20は既知照合資料。両者は方法選択で、新成功/holdout標本にしません。新hashsource・fresh診断・word/blue条件はgoalでも検査し、実Cancel/同client/入力epoch/newseq/元End意味は維持しています。confidence1はbinary predicateです。

既知実MSS END PHASE2枚は青割合.6927/.7066が陽性でもword .6676/.6734で拒否。旧帯なしDraw20は旧経路を維持、赤End応答/wordあり青欠測/modal証拠欠測/別seq/hash/実入力欠測を回帰しました。実相手DrawやMAIN/BATTLE/STANDBY大帯は未検証、赤化・反転・shiftは合成負例として区別します。安全な新規評価pathの単一比較記録は`evaluation/solo-draw-overlay-shape-diagnostic-v1.json`と`solo-draw-overlay-known-end-negatives-v1.json`。原訓練欠測81+1は変更していません。

typed pending対象75pass、最終対象175pass29.28秒、通常ユーザー全回帰592pass/4skip100.26秒、compileall成功。lint/型検査ツール未導入。固定`evaluation/solo-basic-fixed-v3.json`、UTC2026-10-05T21:09:07.971420+00:00、base `artifacts/solo-basic-calibration-v4`、source `c2942844c9787913959acbc9a2cb9f0f0367b4e7de07851dcf89a04a49cabba7`、components `34e04102c3ea8f0738630e8edd9c7831798e04188dfd411a10cd68dd1135cc68`、Draw config `b9de9c0c5a9d9d792838996f41747ff1332687712d58b252dc5bdc541dab30eb`。code/assets/helpersを停止し、別の相手Endを固定後新MSS10→freshpreflight→新1pilotで評価します。旧失敗を再開成功へ数えず、新版実機成功はこの固定時点で0です。

## 陽性selfDrawへの直接結合（共通固定v4）

v3End実機pilotも1Cancelは適正・受理でしたが、elapsed3418.651ms/成功E2E nullで停止。元runtime seq23/24は自Draw＋DRAW PHASE帯、word1.0/selfblue .734375、残るCancel文字0。旧modal_absent床RGB .977614/.978855だけが拒否を起こしました。395安定画素のうち平均B差.0391/.0368など背景色に依存したproxyであり、LPや手札枚数はROI外なので原因と断定しません。最後の実取得画像・stateは保全し、停止後Main1へ置換していません。`evaluation/solo-end-modal-background-diagnostic-v3.json`。

このrunは内部union2139.249ms、verifywall3190.081ms、残差1215.928ms、そのうちpoll1208.485ms、verify未計測7.444ms、その他未分類63.473ms。predicateは5.174msでした。前runと条件が違うためE2E改善量を主張せず、残差をpuregameとしません。

目的を実際の遷移へ結び付け、明示`evidence_mode=observed_self_draw`を相手End→自Drawだけに追加しました。前End全文・実Cancel・新sequence・同client/epoch・固定source/hash・陽性Draw＋自己側青表示をANDし、残る元End/召喚全文やCancel、既知の別promptは明示的矛盾として拒否します。unknownを消失根拠にせず、phase/player/activeだけを陽性Drawから生成し、prompt/animationはunknownのままです。次入力のprompt/idleガードは維持します。床色はconfidence0と未閾値診断factに残し、完了条件へ使用しません。旧default/召喚辞退/normal/phaseは従来条件です。

新画像資産や閾値は追加・変更していません。旧Draw20は直接Draw陽性、無傷before/未知61はDraw陰性・Cancel等の矛盾陽性。既知失敗画像は方式比較であり、新版実機成功ではありません。比較`evaluation/solo-direct-draw-transition-comparison-v1.json`のコマンドは保存後cleanupのimport漏れでexit1でした。保存値・固定再検査は完了していた点と区別し、`solo-direct-draw-transition-execution-v1.json`に記録しました。成功exitとは扱いません。builder初回は既存composite最少2fact条件で書込み前に拒否され、その条件を緩めず専用Draw modeへ直接接続しました。

unknownpromptでsynthetic目的確認・次入力拒否、残留UIありDraw、不正hash末尾、旧sequence、実入力なし、blueなし、stale診断、legacymode拒否、trials/ledgerの明示modeを回帰。対象178pass18.61秒、最終限定44pass11.15秒、通常ユーザー全回帰616pass/4skip112.94秒、compileall成功。lint/型検査ツール未導入です。

固定`evaluation/solo-basic-fixed-v4.json`、UTC2026-10-05T21:29:18.772976+00:00、base `artifacts/solo-basic-calibration-v5`、source `c3acec46294c7a6856038601a10785fcc41444923d6b0ab32c37f23ebc82a370`、components `9395f92ef04eb0b62a5e915ab5bae9dbfa1a809a1a3d940183bfce0fb67e3120`、route `3a179c2189c438e56c8f65a041b7285f8789c5eaa85d72e808f0d055372e9297`。rawcal/画像/UIpolicy/Draw・Cancel configは前版と同値。元訓練81+1欠測は保持。code/assets/helperを停止し、別Endから固定後新MSS10→freshpreflight→新1pilotをTesterへ通知しました。新版実機成功は固定時点で0、100代表目標は未達です。

## 応答verifyの通常召喚探索省略（共通固定v5）

v4実機End辞退は登録1目的/1入力で独立確認成功、E2E2527.866ms。内部1610.495ms/capture492.403ms/recognition1021.406ms、poll906.303ms/verify未計測5.170ms/未分類5.898ms、retry0。afterseq18青Draw・元UIなし、prompt/animation unknown維持。実機認識19回はp50 54.347/p95 61.344/max74.389ms。1試行で99%や100代表達成とはしません。

認識には全体spanだけがあり、ROI別の実機分解はありませんでした。保存before/confirmed after2枚へメモリ内wrapperを付けると、通常召喚UI bank探索が再生認識の約90〜95%でした。詳細wrapperはobserver負荷を伴うため、10pair順序反転のbare対bankトップだけの計装も実施。before bare59.346ms/トップ58.215ms(bank53.102)、after60.343/60.499(bank55.026)で、最大箇所を確認しました。保存2枚の範囲を越えて実19フレームを再現したとは主張しません。`evaluation/recognition-stage-readonly-replay-v4.json`と`recognition-observer-comparison-v4.json`。

現在actionの宣言LogicalResponseDeclineとactive ledger一致時のverifyだけ、normal UI bankの局所探索を省略します。固定asset stat guard・generic ROI・詳細registry・元全文/Caption/Draw・既知prompt矛盾検査は維持。summon_enabled/hand_selectedは取得時刻に一致したunknownへ上書きし、古いcache陽性や座標proofを使用しません。初回candidate、normal、phase、その他goalは従来通り。子span`normal_ui_bank`は探索省略/明示scopeとguard時間を記録し、親recognitionと内部unionで重複加算しません。

対象初回2fail/172passは、saved imageへcaptured_at1を付けたfixtureを既存guardが拒否した件と、clone配置による相対registry path不備です。元画像・production条件は変えずoffline0/元guardとtemp bank参照を正しました。失敗XML保持、最終174pass17.25秒。scope偽装/ledger不一致/旧cache/asset改変/他default/子span unionを回帰しました。全回帰631pass/4skip117.14秒、compileall成功、lint/型検査ツール未導入。

保存2画像のdefault対scopedを20pair順序反転で比較し、応答意味signatureは全一致。cold before57.907→5.838ms、after61.962→6.321ms、warm56.942→3.860/61.522→4.090ms。bank guard .93〜1.07msは残しています。差52〜57ms/回はmicrobench値で、実機E2E改善量ではありません。`evaluation/response-scope-saved-pair-comparison-v1.json`。

固定`evaluation/solo-basic-fixed-v5.json`、UTC2026-10-05T22:02:34.651953+00:00、baseは`artifacts/solo-basic-calibration-v5`のまま。source `f06abffb87445d4b5799e582e5839d1ea16839baf994e172810589b9397c4cf9`、components `1013228c37db2428c8d68ef6e88ef2890b1c92ea2093c5367f9e6316505a494f`。cal/route/UI/画像assetは前版同hash、雷電龍機能は未実装。code/assets/helperを固定し、別End新MSS→preflight→1pilotをTesterへ通知。新性能版実機成功はこの固定時点で0、100代表目標未達です。

固定後v5実機1目的は独立レビューで成功（run `9fd57910c8f5479097317f4106ebb92b`）。E2E2614.9034ms、内部988.3830ms/capture667.7484ms/recognition235.7770ms、poll1609.6701ms/verify未計測11.2151ms/未分類5.6352ms。actualCancel1/retry0、元modalなし・青Turn4Draw/帯を確認。初回full bank1、verify探索省略32で意図どおりの経路でした。bank子union70.4443msを親recognitionへ加算しません。前v4比では内部-622.1118ms、E2E+87.0374msですが、表示条件・観測回数が違うので因果改善量とは呼びません。目標内の成功1件を100代表/99%達成に換算しません。`artifacts/baseline-tester/SOLO_END_PILOT_v5_20261006/tester-review.json`。

## 雷電龍手札①の限定pilot準備

独立型`LogicalHandSearchConfirmation`はACTIVATE→専用の自分雷電龍チェーンCANCEL→自動サーチの公開face/移動/手札収納→実手札inspectを1目的として扱います。今回の実資料ではサーチ選択UIは表示されず、選択/確定入力を追加しません。候補提示は公開された有効effect・詳細CID13906・選択カード局所形状による別modeです。旧strict ruleのunused/deck残数などunknownは書き換えません。詳細絵の照合は公開左panelだけで、手札の小画像を単体CID証拠にしません。

原Native129枚は方式選択資料、全原hash確認済み。公開4枚と連続移動から同instanceのhandoffを追跡し、収納後の実inspectと新しい詳細を結び付けます。入力receipt/epoch/seq/client/固定hash・前ready/陽性detail blank・可視safe point・同X帯選択矩形をANDします。使用済み表示/手札枚数復帰だけでは追加成功にしません。外部入力epochは不透明な活動tokenで全入力不在の完全証明ではなく、input_sentはbackend呼出完了の記録でゲーム受理は画面結果で別確認します。

全手札RGBのsource/ready/selectedはdiagnosticのみ。readyでは右隣に隠れた外枠を捏造せず、実handoffに沿う上辺/左辺の可視内側をbbox/pointへ使います。source/selectedの完全接続矩形条件は緩めません。初期対応はnative1280×720・source手札6/7枚slot3の既知effect配置です。destinationはsource slot番号を使わず実handoffから決定します。手札7のgeometry/detail陽性でも現在のMain1 contextがunknownの資料では操作を拒否します。手札6readyの診断bboxはsyntheticで、実handoff6の連続資料を取得できたとは主張しません。別slot・未知UI・public anchor取り逃し・300ms超gap・品質/位置の多義・epoch/seq変更は停止します。間引き再生で観測位相により点数不足になる制限があり、初pilotで実framegap/anchor/trace/失敗を保存します。

収納形状からglobal animation=Falseは生成しません。第三SELECT_CARDだけ、animation unknownを保持し、前の実ACTIVATE/CANCEL receipt・handoff・同frameの安全point/proof・blank・fresh ready・自分Main1を根拠にinspectを許可します。animation=True、別Action/source/promptは拒否し、source/CANCELと旧normal/response/phaseのidle条件は維持します。confidence1はbinary predicateで確率や一般カード識別精度ではありません。

pilotは最大3子入力/1目的・retry0・実行20秒・各verify上限8秒・poll .05秒・settle0、fps引数30。8秒は結果を観測する診断上限で3秒KPIとは別です。fpsは要求値で実周期保証ではなく、原訓練採取もPNG保存込み平均81.177msで40fps未達でした。固定後に別新MSS10入力0→fresh preflight入力0→別新取得から1pilotを実施します。preflightは別trialで、正式100の分母へ換算せず、将来cohortでは画像選別の前に同attemptをadmitする必要があります。実機pilotはTester専属です。

固定後の新MSS10はdetailとgeometryの独立不足で開始0/10、操作0でした。位置ずれではなく非一様色変動でdetail RGB距離が低下しました。thumb全体のSIFTは共通枠/印刷部だけでも別CID46を全許可し、不採用です。新明示modeはnative detail thumbnail内のart[12,30,78,72]だけへdescriptor全支持を制限し、参照特徴をcacheした局所勾配対応を旧RGB .98とORします。forward Lowe ratio .75＋reverse nearestの相互一致を使い、両方向Lowe ratioではありません。affine/inlier数・比率・位置/scale・art内spreadをANDし、少featureとNoneはunknownです。枠/星/本文はこの枝の証拠にしません。新10はここから方式選択資料でありholdoutではありません。旧1枚は両枝unknownを保持します。

detail単位の54テストとcompileは成功しました。保存10画像の同条件microbenchではrecognize平均8.782→13.323msで追加4.541msです。これは取得/実入力/結果画面を含まないlocal CPU値で、E2E高速化ではありません。geometryは未解決の別工程であり、開始経路全体を修復したとは扱いません。元profile/元画像は維持し、次独立MSSと実機pilot前には新版全回帰・source/条件/資産固定が必要です。

続くsource限定modeでは、左detailで確定したartと、選択hand内の実表示artの対応をEffect位置へ結びます。`source_art_pose`に実art bbox/モデル/参照hash/原frameを持ち、見えないfullcard外枠へ変換しません。現在のdetail/有効Effectがないframeはnot_applicableでsource検出を省略し、unknownをfalseや陽性へ書き換えません。異位置の同名候補は拒否し、同義参照の同位置だけ統合します。最大clusterだけ選んで弱い候補を隠さないnegative-only probeも有限反復で確認します。selected7のart所属が陽性でもEffect無しならaction0、旧unknown2枚も保持します。GY/unknown・stale Main1/同frame/native/epochの入力guard、ready/selected endpoint/実receiptは維持しています。

最終全回帰748pass/4skip200.66sとcompile成功。新profilev4を`evaluation/hand-search-fixed-v2.json`で固定しました。単独source/verify保存画像microbenchは平均8.007→17.081ms/8.251→5.516msで、前者は支持追加のコスト、後者はsource-only短絡を含む結果です。E2E改善量ではありません。先のv1はfullsuite開始と終了回収が重なったため負荷独立性未証明の参考値とし、原数値を保持したsidecarを残しました。固定後新MSS→freshpreflight→1pilotをTesterへ渡し、実機結果前の成功・100代表達成は主張しません。
