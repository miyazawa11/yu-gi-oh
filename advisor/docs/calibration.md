# 実画面の校正

合成デモは実ゲーム配置を含みません。対象の解像度、UI言語、表示モードごとにデータを分けます。`snapshot` で実画面を保存し、画像編集ツールで領域の画素座標を測ります。ツールはゲームを操作しません。

領域の `(x,y,width,height)` は **viewport 内で**それぞれ横幅／縦幅で割った値です。既定 viewport はフレーム全体、比率16:9です。黒帯を含む画面は `--viewport x,y,width,height` を指定し、ゲーム内容が16:9となるよう切り出します。例: 640×480に高さ360のゲーム表示なら `0,0.125,1,0.75`。実測した領域を指定し、例の座標を実ゲームへ転用しないでください。

```powershell
# 座標は説明用。実画面で測った値に置き換える。
.\.venv\Scripts\python.exe -m master_duel_advisor calibrate-region --calibration data/layout.json --image data/screen.png --region self.lp --kind number --box 0.10,0.80,0.10,0.05
.\.venv\Scripts\python.exe -m master_duel_advisor calibrate-region --calibration data/layout.json --image data/main1.png --region phase --kind template --label MAIN1 --box 0.85,0.45,0.10,0.05
```

同じ領域の別ラベルを追加すると画像ファイルを上書きせず exemplar が増えます。同じラベルの複数サンプルも可能です。領域の場所や kind を変える場合は別 layout を作ってください。テンプレート登録画面と評価用画面は分離し、未知／非アクティブなケースも含めます。

認識対象:

| フィールド | kind | ラベル |
| --- | --- | --- |
| self.lp / opponent.lp | number または template | template時は数値文字列 |
| turn | number または template | turn number |
| self.hand_count / opponent.hand_count | number または template | count |
| turn_player | template | self / opponent |
| phase | template | DRAW / STANDBY / MAIN1 / BATTLE / MAIN2 / END |
| self.zones.NAME / opponent.zones.NAME | card | DBのcard_id |
| action.NAME | action | NORMAL_SUMMON / SPECIAL_SUMMON / ACTIVATE / SET / ATTACK / CHANGE_PHASE / SELECT_CARD / SELECT_TARGET / CONFIRM / CANCEL |

zone NAME には hand_1、monster_1…5、spell_trap_1…5、extra_monster_1…2、graveyard、banished、extra_deck 等を使えます。画像に見えている個別カードを表す領域のみ登録し、一覧全体からカード1枚を推測しないでください。認識未対応の領域は kind=unobserved として表現できます。テンプレートのない領域や非表示のカードは unknown のままです。

action は操作可能な見た目のボタンだけを登録します。ハイライト、無効化、演出、他の選択 UI と似ている場合、操作不能な場面のテストデータ を追加し 類似度のしきい値（threshold）と次点との差（margin） を調整してください。1枚のテンプレートで合法性を証明したとは扱いません。未校正画面に類似ボタンがあっても候補が誤検出され得ます。

カードメタデータ:

```json
[{"card_id":"your-card-id","name":"カード名","type":"monster","attribute":"DARK","race":"Fiend","level":1,"rank":null,"link":null,"atk":300,"defense":200,"effect_text":"ユーザーが登録する効果文"}]
```

`import-cards data/cards.json --database data/cards.sqlite3` で取り込み、card 用テンプレートの label と一致させます。参照画像を自動取得する処理はありません。

`validate-calibration data/layout.json --database data/cards.sqlite3 --image data/screen.png` を実行し、geometry/semantic labels/assets を確認します。実精度は別途 `evaluate` が必要です。

正解ラベルの例（値は人間が画像から付け、予測結果から転記しない）:

```json
{
  "kind": "real_game",
  "samples": [{
    "image": "holdout/frame001.png",
    "expected": {"self.lp":8000,"opponent.lp":5200,"turn":3,"turn_player":"self","phase":"MAIN1","self.hand_count":5,"self.zones.monster_1":null},
    "actions": [],
    "recommendation": null
  }]
}
```

画像が示す各対応フィールドをラベル付けしてください。nullは明確に認識不能なケースです。actions/recommendation は今回の限定 UI ルールに対する正解であり、最善手の正解ではありません。サンプル数を十分に集め、実ゲーム精度未達なら校正・前処理を改善します。
