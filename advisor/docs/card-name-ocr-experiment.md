# ローカルカード名OCRの最小実験

選択されたカードの左詳細panelの名前行だけをOCRし、ローカルDBの日本語名と完全一致した場合だけCID候補を返す実験。runtime、既存校正、telemetryには統合していない。入力0、画像の外部送信0、実機E2E標本0。postにはこの名前行が無いため無理にOCRしない。

既存実行バイナリは`C:\Program Files\Tesseract-OCR\tesseract.exe`、version5.4.0.20240606。PATHやProgram Filesを変更せず`--tessdata-dir data/ocr/tessdata_fast`で日本語modelだけを指定する。

[公式tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast)と[公式data説明](https://tesseract-ocr.github.io/tessdoc/Data-Files.html)を確認し、公式repoのcommit`87416418657359cb625c412a48b6e1d6d41c29bd`からjpn.traineddataとApache-2.0 LICENSEをプロジェクト内へ保存。model SHA256は`1f5de9236d2e85f5fdf4b3c500f2d4926f8d9449f28f5394472d9e8d83b91b4d`、2,471,260bytes。URL/取得日時/commit/hashは`data/ocr/tessdata_fast/source.json`。OEM1を使用し、OSDや別の実行バイナリを追加していない。

## 固定設定と資料分離

`scripts/benchmark_card_name_ocr.py`は局所ROI→3倍raw画像→PSM7/OEM1/jpn→TSV→DBexact name。NFKCと空白除去以外の文字補正・部分一致・fuzzyを行わない。同名が複数CIDならambiguousとして拒否。confidenceは各OCR単語の最低値を使用し、.90未満を拒否する。

このconfidenceはTesseractの未校正scoreであり、正答確率でも成功率99%の保証でもない。画像matcherの.98とは別の尺度。正しい名前が出力されてもconfidenceが低ければCIDを採用しないため、文字列exact一致率と採用率を別に記録する。

G/Solar各20枚の先頭5枚だけでraw/gray/otsuと少数のscale/PSMを比較した。raw3x/PSM7はtrain10/10文字列exact、.90 gate採用3/10。grayは空文字、otsuは末尾ノイズ、raw2はexact5/10、raw4はexact10/10でも採用0/10、PSM13はexact0/10。raw3x/PSM7/.90をeval未使用で`evaluation/card-name-ocr-fixed-settings-v1.json`へ固定した。調整はtrainだけで行い、eval後に閾値を下げて通す変更はしていない。

`card-name-ocr-manifest-v2.json`はG/Solar各5train/15eval、新Driver/Ash/雷電龍のfirst各3train/reopened各3eval。G/Solarは同じ取得burstの画像分割、新資料は後刻再表示の分離だが方式固定前の取得なので、正式な独立holdout精度とは称さない。Driver/雷電龍は名前の横scrollで単frame全名を保証できず、unknown棄却を期待する。カード自体のgroundtruth CIDと、名前ROIから期待するunknownを区別してmanifestへ記録した。

初回試行は新tessdataに`tsv`configがなく、stderrの`Can't open tsv`により出力を読めなかった。ログを保存し、config追加ではなく`-c tessedit_create_tsv=1`でTSVを生成するようhelperを修正。この初回失敗の0%を日本語modelの精度として扱わない。

## 固定eval結果

39画像を各3回、117calls。読み取りはすべて名前ROIのみ。画像ファイルの読込/復号は時間の対象外、ROI変換/PNG生成/実行process起動・model読込/OCR/parse/alias lookupを含む。

| 指標 | 結果 |
| --- | ---: |
| 全名の文字列exact一致 | 26/33（78.79%） |
| confidence gate後の全名CID採用 | 8/33（24.24%） |
| partial headerの安全な棄却 | 6/6 |
| 誤ったCIDへのalias確定 | 0/39 |
| 初回OCR呼出し | 185.163ms |
| 平均 / p50 / p95 / 最大 | 176.448 / 177.377 / 185.600 / 200.160ms |
| 反復呼出し平均 | 176.690ms |

各呼出しでprocess/modelをロードする。初回は物理的cold cacheを保証せず、反復は常駐OCR engineの性能ではない。同一画像の反復を精度の独立標本数へ加算しない。

| カード | 文字列exact | CID採用 | 主な失敗 |
| --- | ---: | ---: | --- |
| G9455 | 9/15 | 8/15 | 末尾`「`/`]`のOCRノイズ6、低confidence1 |
| Solar13581 | 14/15 | 0/15 | 低confidence14、誤字末尾1 |
| Ash12950 | 3/3 | 0/3 | 低confidence3 |
| Driver12067/雷電龍13906 partial | 全名保証なし | 0/6 | blank_ocr6、安全なunknown |

平均の内訳はROI/PNG生成1.696ms、engine起動/model読込/OCR174.636ms、parse/alias lookup0.116ms。最も長い計測区間はengineであり、改善を検討するならこの区間を実測で分解する。現段階の採用率ではruntimeへ組み込まない。未知・切れた名の安全拒否を維持し、画像templateによる第2証拠は将来の別実験とする。

## 再現コマンド

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/benchmark_card_name_ocr.py --manifest evaluation/card-name-ocr-manifest-v2.json --database data/decks/thunder-dragon-review/cards.sqlite3 --variant raw --scale 3 --psm 7 --split eval --output evaluation/card-name-ocr-fixed-eval-v1.json
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_card_name_ocr_experiment.py -q
```

JSONと同名JSONLへ全呼出しの文字列、confidence、CID、期待CID、failure_reason、stderr、各処理時間を保存。実行model、binary、DB、manifestのhashも記録。未知名やfuzzyを自動確定するロジックはない。
