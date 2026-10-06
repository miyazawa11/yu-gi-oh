# 選択詳細名の小レジストリ

`DetailNameRegistry`は左詳細欄の名前ROI `[24,106,217,24]`だけを、固定3参照（KONAMI CID9455/13581/12950）に照合します。1280×720のBGR uint8画像を前提に、既存`fingerprint`で64×32に縮小し、`1-mean(abs(diff))`を計算します。score≥.98かつ別CIDのtop1-top2≥.03を満たす場合だけCIDを返します。これは画像類似度であり、校正済みの成功確率ではありません。

返るCIDは表示中の詳細カードだけを意味します。手札slot、所有者、所属ゾーン、合法手を確定しません。Action、GameState、既存校正、戦略、入力へ接続していません。フレームごとの不変evidenceにCID/候補/score/top2/margin/ROI/frame_seq/observed_at/registry hash/参照hash/棄却理由を含めます。CIDをキャッシュせず、未知/曖昧/不正shape/dtype/時刻にはCID=Noneを返します。observed_atは取得元の単調時計時刻をそのまま保持し、鮮度や実機前面適格性はこのライブラリでは保証しません。

固定assetは`artifacts/detail-name-registry-v1/registry.json`、SHA256 `86e6cc60a004b0d8aff769bd6ee0b0d8c0653f136199cae9af612e47babd6950`。schema/source/KONAMI namespace/ROI/shape/特徴方式/閾値/3CIDを読込時検査し、参照cropのhashとsizeを検証します。manifestには参照元全画像hashと公式CID出典を記録しています。未知カードを近い参照へ無条件に割り当てません。

```powershell
.venv\Scripts\python.exe -X utf8 scripts/build_detail_name_registry.py --output artifacts/detail-name-registry-new
.venv\Scripts\python.exe -X utf8 scripts/evaluate_detail_name_registry.py --registry artifacts/detail-name-registry-v1/registry.json --manifest evaluation/detail-name-exploration-manifest-v1.json --output evaluation/detail-name-exploration-v1.json --repeats 100
```

評価manifestは`purpose`と`frames`を持ち、各frameは`image`（advisor基点path）、`sha256`、`expected_cid`（文字列またはnull）を含みます。評価は画像hashを確認します。出力mode=offline_saved_image/usable_for_input=false。observed_at=0は保存画像の取得時刻不明、frame_seqはmanifest順序であり実capture番号ではありません。現在monotonicで保存画像を新鮮な観測にせず、perf_counterは局所処理時間にのみ使います。Driver/雷電龍のpartial名と名前非表示はnullで評価します。参照cropは生成後に固定し、評価画像で再調整しません。

旧探索画像75枚（正例43、Driver/雷電龍partial12、名前なし20）では75/75一致、誤CID0。正式独立holdoutではありません。画像読込・復号を除いたROI特徴+3照合+evidence構築7500回の平均.052911ms/p50.03675/p95.1283/max.7772ms。反復を精度標本数に加算しません。画面取得、E2E、UI操作、結果確認の速度や成功率を示す値ではなく、入力0/E2E0です。固定後の新実機Ash/partial/blank検証と、別解像度・別表示への適用は未検証です。

局所unit/integration11件成功。全体回帰351件成功4skip（38.03秒）、その後offline evaluator証拠の追加回帰を局所11件で確認。compileall成功、lint/type checker未導入。全体XMLはevaluation/detail-name-host-tests.xml。固定source SHAac8d0752039ffc64b38bcf9744a417c231a6853b66ae45d0c5ae75e8f038491f、各helper/module/hash一覧はevaluation/detail-name-fixed-hashes-v1.json。既存OCRとの統合や第二証拠化は今回行いません。
