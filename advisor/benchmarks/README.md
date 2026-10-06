# E2Eベンチマーク

KPIの1アクションは特殊召喚など目的達成全体です。素材選択等の子クリック数ではありません。実機の校正と各目的の完了証拠が必要で、現時点の超雷龍ルートは不足校正により実機起動ゲート未達です。

取得前の試験予定例は`colossus-trials.json`。自律loop起動時に既存引数へ`--benchmark-trials benchmarks/colossus-trials.json`を追加します。これは操作方針には介入せず、初期認識失敗も試行分母へ記録するための予定です。既存`--max-actions`は子UI操作上限です。

集計（ゲーム入力なし）:

```powershell
.venv/Scripts/python.exe -X utf8 -m master_duel_advisor e2e-benchmark artifacts/<run>/logical-actions.jsonl --output evaluation/e2e-baseline.json
```

複数runのログも指定できます。同じaction_idの二重読込みは拒否します。予定なしの観測ログ、補助操作、合成試験からはKPI合格を出しません。

誤クリックの独立レビューは1子入力につき次のJSONL形式です。step_idは実ログの値、evidenceは実際に確認した前後画像/動画と判定根拠、reviewerは判定者を記録します。送信結果不明もレビュー対象です。

```json
{"step_id":"実ログの子入力ID","misclick":false,"reviewer":"判定者","evidence":"前後画像の参照と判定根拠"}
```

```powershell
.venv/Scripts/python.exe -X utf8 -m master_duel_advisor e2e-benchmark artifacts/<run>/logical-actions.jsonl --reviews evaluation/input-reviews.jsonl --output evaluation/e2e-reviewed.json
```

平均/p50/p90/p95/最大、成功率、誤操作率（親目的）、誤クリック率（子入力）、再試行率、fallback率、stage平均、失敗ケースと各gateを出します。未レビューはunknownのまま不合格です。成功E2Eと全attemptelapsedを併記し、早期失敗が平均を短くしても成功E2Eの閾値を別に満たす必要があります。

詳細・baseline前提・計測限界は`docs/benchmark-baseline.md`を参照してください。
