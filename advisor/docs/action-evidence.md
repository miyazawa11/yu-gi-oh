# 召喚候補位置の証拠（A1、入力未接続）

`ActionEvidenceDetector`は固定G/Solarの既存`action.normal_summon`を局所探索します。既存Perception、Action、AgentLoop、校正、3rule、LogicalZoneTransition、安全ガードには接続しません。返るのは`NORMAL_SUMMON`候補と位置の画像証拠で、カードCID、所属ゾーン、合法性、クリック点は生成しません。`usable_for_input`はliveでも必ずfalseです。

設定は`evaluation/action-evidence-detector-v1.json`、SHA256 `38ac24d4a30f0606a8d46cd4c1dfcf16c1289cf6528f8c5e844a434867f38e1f`。Gの証拠ROIは `[434,496,73,98]`、Solarは `[380,497,74,79]`。この矩形は画像照合用のcropであり、ボタン全体の境界ではありません。固定BGR uint8 1280×720のみを扱います。

探索は元位置からx±64px/y±24pxの4px刻み、最高候補の±3pxを1px刻みで精探索します。精探索は元の探索範囲を超えません。旧64×32 BGR特徴とstable_rgbのprototype/maskを再使用し、有効画素のみのMAEを計算します。score≥.98、別位置とのmargin≥.03を要求します。幅の半分または高さの半分以上離れた位置を別仮説としてrunner-upにし、隣接windowを独立ボタンとして数えません。

特殊召喚、反転召喚、無効な通常召喚ボタンとの種類競合は未検証です。そのため`type_runner_up/type_margin=null`と`unverified_alternatives`を記録します。位置marginを操作種類のmarginと混同しません。Solarの参照はGの召喚ボタンにも一致するため、参照profile名をCID証拠にしません。召喚の文字だけから通常召喚を確定する仕組みでもありません。

不変のButtonEvidenceにscore、位置runner-up、margin、検出crop、探索crop、frame_seq、observed_at、capture_source/clock/sequence意味/client矩形、detector/profile hash、棄却理由を保存します。通常のasset変更をsize/mtimeで検出し、評価の開始・終了では設定、校正、全参照画像の内容hashも照合します。size/mtimeを同時復元する意図的変更の即時検出は保証せず、full_hash検査で検出します。prototype/maskは変更不可にし、毎Actionのファイル読込やOCR/LLMを導入しません。

`CaptureContext`はliveとofflineを明示します。liveはFrameの実monotonic受領時刻、実capture sequence、client矩形とshape整合が必要です。ただし、この宣言だけで前面やクリック安全性は保証しません。保存画像評価はFrame(captured_at=0, sequence=manifest順序)で行い、`unspecified_zero_not_capture_time`と`manifest_index_not_capture_sequence`を記録します。保存画像へ現在monotonicを付けた入力は拒否します。perf_counterは局所処理時間だけに使い、取得時計へ流用しません。

評価は次のコマンドで実行します。

```powershell
.venv/Scripts/python.exe -X utf8 scripts/evaluate_action_evidence.py --config evaluation/action-evidence-detector-v1.json --manifest evaluation/action-evidence-exploration-manifest-v1.json --output evaluation/action-evidence-exploration-v1.json --repeats 3
.venv/Scripts/python.exe -X utf8 -m pytest tests/test_action_evidence.py -q -p no:cacheprovider
```

探索manifestは40枚の元menu訓練、Researcher目視のボタンなし4画像×2profile=8照合、同じmenu2枚の右SET crop診断=2照合を分けます。合計50case/44unique画像であり、「独立50画像」や実機50目的と扱いません。反復処理時間は精度の分母へ加算しません。crop診断は探索で見つけたActionでもありません。画像読込・復号・取得、UI入力、画面上の結果確認は局所時間から除外します。

局所探索の追加時間は固定ROI照合との差として記録します。認識範囲を増やす基盤であり、速度改善を主張しません。最新数値は`evaluation/action-evidence-exploration-v1.json`にあります。入力0、E2E0、100代表目的の受入は未達です。

固定探索50case/44unique画像は全一致。144callsの探索平均33.407ms/p50 33.275/p90 35.328/p95 35.902/最大40.309ms、同一入力の固定ROI平均0.186msで、追加約33.221msです。固定後の新Ash・同対戦3枚は採用有無3/3、最小score .996274/margin .237895、探索平均33.087ms。Researcherはbbox原点を独立確定できず、3枚すべてposition_unverified、joint_position_passed=falseです。別対戦・未知召喚種別・入力成功への一般化は未検証です。詳細は`evaluation/action-evidence-ash-holdout-v1.json`。

通常ユーザー環境の全回帰380passed/4skip（41.81秒）、最終新規28テストを含みます。制限環境は370passed/9failed/4skipで、失敗9件は既存DPAPI credential_protection_failedです。XMLは`evaluation/action-evidence-{all,host}-tests.xml`。compileall成功、合成demo4/4・実機gatefalse、ruff/mypy/pyrightは未導入でlint/typecheck未実行です。新module以外の既存Python sourceのhashはac8d0752…のまま、追加後source SHA256 `6c9116cafe0c297f530608b0e4b2ec21831fc9abc059c544e468511a78fdc979`。固定hash一覧は`evaluation/action-evidence-fixed-hashes-v1.json`。

## 独立holdoutのmanifestと手順

1. 方式・設定・module SHAを固定した後にTesterだけが前面MSSで新client画像を取得します。同じ画像を新時刻で再利用せず、固定後の資料を訓練へ追加しません。
2. 原capture manifestに画像file/hash、eligible、shape、foreground/rect前後、UTC開始時刻、実captured_at_monotonicと時計名、実capture sequence、perf_counterの開始/終了を別々に保存します。
3. Researcherが検出score/位置を見ず、有効な通常召喚、SET、未知/無効等を目視ラベル付けします。期待cropを独立確定できない場合はnullとし、position_groundtruth=unverifiedを指定します。
4. 下記schemaへ整形して同じ評価CLIへ渡します。imageは評価manifest基点、original_capture_manifestは原資料の場所です。collector、fixed/collection/frameのUTC時刻を必須にし、固定前の取得を拒否します。

```json
{
  "schema": "action-evidence-evaluation-v1",
  "dataset_kind": "independent_holdout",
  "purpose": "固定後の新Ash menu、位置精度は未検証",
  "detector_sha256": "38ac24d4a30f0606a8d46cd4c1dfcf16c1289cf6528f8c5e844a434867f38e1f",
  "frozen_at_utc": "2026-10-05T17:51:30.841731+00:00",
  "collector": "RealDeviceTester",
  "collection_started_utc": "2026-10-05T17:52:00+00:00",
  "frames": [{
    "image": "frame-0000.png",
    "sha256": "実画像のSHA256",
    "profile_id": "solar-menu-v2",
    "sample_role": "independent_holdout",
    "reviewed_label": "自己Main1/Ash menu、召喚有効、SET別操作",
    "capture_start_utc": "2026-10-05T17:52:00+00:00",
    "original_capture_manifest": "manifest.json",
    "expected_detected": true,
    "expected_evidence_bbox": null,
    "position_groundtruth": "unverified",
    "bbox_tolerance_pixels": 3
  }]
}
```

画像hash・設定hashを照合してから評価し、detector/calibration/assets/stable特徴と関連component source hashesを結果へ残します。`detection_passed`は採用有無だけ、`joint_position_passed`は位置までの一致です。未検証bboxは`bbox_passed=null/position_validation=false`で位置合格に数えません。CLI exit0は採用有無の合格だけを意味します。この画像評価から入力可否・結果確認成功へ昇格しません。

## A2に必要な最小接続

次は、自分Main1で既知低級カードの有効通常召喚menuから開始する限定1目的を優先します。開始点をmenuへ置くことで手札slotの未検証推定を避けられますが、source所属の証拠、通常召喚履歴、召喚種別の安全な限定は別途必要です。旧normal_summon3ruleとfieldCIDの条件は維持し、新normal_inspect_confirmation等のprofileを分離します。

必要資料は同一取得元の①現在menuの詳細CID＋self/Main1文脈＋有効召喚UI、②配置画面のprompt/合法な指定zone、③指定zoneの直前emptyと直後occupied、④実際のzone選択・inspect入力が送信されたreceiptと新sequence、⑤選択highlight等で実zoneと結び付いたdetailCIDです。detailCID単体はfield/hand所属を生成しません。同じCIDと占有が見えても、実際の召喚種別が正しい証拠なしに目的成功へしません。

入力接続時にActionの座標証拠を実frame/state sequence・monotonic鮮度・client矩形・操作種別・検証済みprofileへANDで結びます。_coordinatesでは確認済みbutton内の安全点を解決し、既存fixed-cal経路と入力backendの前面/矩形/停止ガードを維持します。bbox精度とbutton内部の安全点レビューは別に行います。

runtimeへ接続する版では、registry/detector config・全assets・stable特徴・component sourceを認識component fingerprintに明示し、取得前freeze、acceptance slot照合、終了内容hashへ含めます。A1は未使用の部品なので既存acceptance設定に追加せず、新Python moduleは既存Telemetryのsource全体hashへ自動的に入ります。
