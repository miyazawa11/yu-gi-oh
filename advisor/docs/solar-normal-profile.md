# 太陽電池メンの局所通常召喚profile

KONAMI CID13581の太陽電池メンを、表示中の局所slot2から中央monster_2へ通常召喚する限定校正。初期画像は隣slot3の孤高除獣がhoverされた同じ画面配置。汎用7枚手札対応、任意の手札配置、未知のカード判断として扱わない。

`scripts/build_normal_calibration.py --profile solar-slot2 --output artifacts/solar-normal-calibration-v1`で生成する。既定の`--profile maxxc`は増殖するG9455の既存profileを保持し、calibration/routeの再生成hashも既存版と一致する。

v1は`artifacts/baseline-tester/MAXXC_CURRENT_HAND_TRAIN_20261006/{initial,solar-menu,solar-placement,solar-post}`の各20枚をSHA照合して生成。SELECT_CARD→NORMAL_SUMMON→CONFIRMの3rule、閾値.98、stable_rgb、中央empty→選択13581→対応配置→occupied+同CIDという既存目的証拠を使用する。fieldCID ROIはclient(609,404,61,45)、占有は(603,398,74,53)。任意効果modalの開始位置より上の実fieldのみを使い、modal内カード絵をfieldの証拠に使わない。

postにはphase/prompt/turn/hand_countの確定値を追加しない。post_evidenceの画像照合だけで実機目的成功とは扱わず、実送信と選択・開始時空ゾーンの履歴はActionTelemetryで別に要求する。自律入力はCoordinatorとTesterによる校正固定後の確認が必要。

入力なし評価は以下（advisorを作業ディレクトリとする）。

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/evaluate_normal_profile.py --calibration artifacts/solar-normal-calibration-v1/calibration.json --database data/decks/thunder-dragon-review/cards.sqlite3 --route artifacts/solar-normal-calibration-v1/normal-route.json --manifest artifacts/solar-normal-calibration-v1/training-manifest.json --output evaluation/solar-normal-training-v1.json
```

新post資料を検査する場合、`--manifest <固定後資料のmanifest.json> --stage post --output <新評価JSON>`へ変更する。helperの独立性表示はunknownであり、収集日時・固定hash・元訓練との非重複を別途確認する。helperは入力を送信しない。

v1は訓練80/80、確認済み負例88/88で開始誤許可・Solar post誤認0。これは訓練/探索資料で、独立精度ではない。既存Gの4段階80枚、既存MSSフェイズ資料6枚、Researcherが目視したphase modal0438と別カードhover1枚だけを負例へ採用した。初期の未分類画像を含む530枚探索はラベル未検証のため正式負例評価として採用しない。確実な空field+chain modalの実画像評価は未実施。

校正固定後の新post3枚はoccupied/CIDとも閾値未達で0/3成功、入力0。v1を実機使用しない。±4px探索では(0,0)最良、modal artは1.0、相手field artは.99996であり、座標や全画面色差を主因とする根拠はない。自field artは.91698、CIDは.93369、occupiedは.94175。自fieldの局所的色/ハイライト変化が大きい。短区間のtrain20枚はその変化を安定特徴として学習したと考えられるが、描画機構の原因を断定しない。`evaluation/solar-normal-post-diagnostics-v1.json`に測定を保存した。

v1校正hashは`cbe7823eabe83a93410ad9612810d94a0263dec4fedb34c754b964a54170cd72`、route hashは`1d5cde7a0306c50053b5afdea24405f12056597497c2033f95de6ac847562a34`。失敗holdoutを保持し、v2は別の時間分散trainから作成して新固定後holdoutで検証する。閾値を下げず、安定mask256画素とCIDを区別できる負例marginを維持する。

## v2の時間分散post

旧20枚と`SOLAR_POST_TEMPORAL_DIAGNOSTIC_20261006`の時間分散11枚（10.098秒）を合わせると、占有の安定maskは304画素だがCIDは72画素で256要件を満たさない。この実測から両表示を同じstable templateへ混ぜる案を採用しなかった。title/枠だけにCIDの根拠を狭めず、v2は新しい黄橙の安定post11枚で同じ実field ROIを学習する。旧青白postは未対応の過渡表示として確認待ちになり、未成立や誤操作とは断定しない。

生成は`--profile solar-slot2-v2 --output artifacts/solar-normal-calibration-v2`。initial/menu/placement各20枚はv1と同じ、新post11枚の計71枚であり、manifestに採用方針を明記する。71/71訓練、負例88/88、旧過渡20/20で安全な確認待ち、旧holdout3/3は既知診断資料として認識。既知診断3枚は訓練に混ぜていないが、v2独立holdoutとしても扱わない。

CIDの正例最小score .999985、負例最大 .758908（観測差 .241077）。占有は正例最小 .999954、負例最大 .793933（観測差 .206021）。両labelのstable maskは2048画素、閾値.98を維持。`evaluation/solar-normal-margin-v2.json`へ保存。

v2固定後の新資料`SOLAR_POST_FIXED_HOLDOUT_v2_20261006`では3/3認識成功。occupied .999973〜.999980、CID .999990〜.999995。これは同じpost画面の新キャプチャで、別対戦の汎用認識や実入力E2Eの成功ではない。入力0/E2E標本0。新対戦でのinitial/menu/placement適合と、実入力から安定postへ到達するまでのtimeout適合は未検証。

v2校正hash `4d82031330e6b67d7eccdf947a00eb60c506419508ec368bd9f8380811bece3f`、route hash `117b3ecff37e5f86543d58709fe924f5fcce55d018ce71b455d045af997dac61`。v1は失敗版としてそのまま保管。src runtimeは変更せず、Coordinator指定のtelemetry集計文言のみ修正済み。最終runtime source hashは`d7c39a500acc6d9ef56f1852ed849b08a371a030fab2fe2efcf01fd852944897`。
