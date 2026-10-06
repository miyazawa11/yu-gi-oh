# カード原文の自動ローカル保存

YGOPRODeck v7の `cardinfo.php` からカード情報を取得し、ローカル優先で再利用します。APIは日本語に対応していないため、英語の `desc` 原文を保存します。通常モンスター等では効果ではなく説明文の場合もあります。

仕様確認元: https://ygoprodeck.com/api-guide/ （確認日2026-10-05）。提供元はローカル保存を推奨し、上限20要求/秒を案内しています。この実装は同一プロセス内で最大2要求/秒・直列通信とし、失敗後は同じ検索を1時間保留します。多数プロセスを同時起動して取得する運用は避けてください。

## 保存場所とデータ構造

既定の共有保存先は、カレントディレクトリによらず `advisor/data/card-knowledge.sqlite3` です。

| 保存先 | 内容 |
|---|---|
| knowledge.provider_id | APIのid（パスコード系）。KONAMI IDとは別の列 |
| knowledge.konami_id | APIのmisc_infoで確認できたKONAMI ID。ない場合はnull |
| knowledge.name_key | 完全一致検索用の英語名 |
| knowledge.record | 下記のバージョン付きJSON |
| failures | 検索種別、検索値、再要求可能時刻、失敗理由 |

recordにはschema_version、provider、provider_version、provider_id、konami_id、language、fetched_at（UTC）、source_url、sha256、master_duel_verified、raw、cardを保存します。

rawは受領したカード1件の全JSONです。効果本文、種別、能力値、収録情報、画像URL、提供元の規制等、返された項目を保持します。画像ファイルそのものは取得しません。cardは既存のCard形式へ正規化し、effect_text、effect_language、effect_source、effect_fetched_at、external_idsを持ちます。XYZのlevel値はrankへ、linkvalはlinkへ対応付けます。

KONAMI ID付きの共有レコードは `konami:13923`、IDなしなら `ygoprodeck:15291624` のように種類を明示します。これらの数値を相互に推測変換しません。旧校正の裸の数値はrun/agent-loopの `--card-id-namespace` に従い、既定はkonamiです。パスコードを使う設定ではygoprodeckを指定してください。非数値のデモIDはAPIに送りません。

## 手動参照でも未保存だけ取得する

advisorフォルダーで実行します。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m master_duel_advisor cache-card --konami-id 13923
.\.venv\Scripts\python.exe -X utf8 -m master_duel_advisor cache-card --name "Thunder Dragon Colossus"
```

1回目は未保存なら取得、2回目以降は保存済み原文を返します。KONAMI ID・英語名・パスコードのどれで検索しても、保存済みの同じカードを再ダウンロードしません。`--passcode`、保存先変更の `--cache`、明示更新の `--refresh` に対応します。日本語名だけではAPI検索せず、公式IDまたは照合用の英語名が必要です。

応答が複数、不一致、本文不足、不正JSONの場合は保存しません。通信失敗や不正応答のあとも古い正常なレコードは保持します。refreshも失敗後の1時間制限を無視しません。API内容は第三者データであり、master_duel_verifiedはfalseです。

## 対戦中の自動取得

CLIのrunとagent-loopで既定で有効です。既存カードDBに十分な本文があれば通信しません。不足時はBackgroundKnowledgeが共有キャッシュを調べ、そこにもなければAPIを呼びます。ゲーム側は完了を待たず、未取得カードは未知のままです。次回参照で取得済みデータをカードDBへ保存し、既存の校正IDと日本語名を維持します。

- 同一カードの要求をまとめ、ワーカーは1個、未完了要求は最大64件。
- 通信はバックグラウンドで、SQLiteの共有キャッシュ接続もワーカー側。既存カードDBへの反映は呼出し元スレッド。
- `--card-cache PATH` で共有先を指定。
- `--offline-cards` は自動取得を切り、指定した既存カードDBだけを使う。
- 既存の評価・デモとCardDatabase単独使用は既定で通信しない。API利用はCLIのrun/agent-loopか、明示的にKnowledgeを接続した場合。
- データ保存は効果条件の実行可能化とは別。現在のLLM入力へ全文を自動追加する変更はしていません。

## 日本語デッキとIDの対応

`scripts/sync_deck_knowledge.py` は、提供されたデッキ転記と英語検索候補を読み、APIのKONAMI IDに対応する公式カードDBの日本語ページタイトルを照合します。名前が一致したカードだけを解決済みとして保存します。曖昧な名前や別カードは失敗として残します。公式ページの効果全文はこの処理では抽出しません。

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/sync_deck_knowledge.py `
  --deck-list data/decks/thunder-dragon-review/deck-list.json `
  --lookups data/decks/thunder-dragon-review/english-lookups.json `
  --output data/decks/thunder-dragon-review
```

出力は `verified-aliases.json`（名前対応・出典・照合時刻）、`deck-list.resolved.json`、`cards.sqlite3`、`sync-report.json`。全件成功した場合のみ `deck-profile.json` を生成します。初回照合後は英語候補から再推定せず、保存済みIDで原文を参照します。元の画像転記ファイルは上書きしません。

新しいカードは同じ手順で追加します。原文更新はcache-card --refresh、その後デッキ同期で既存カードDBへ反映できます。原文の自動期限切れ・定期一括再取得は行いません。

## 運用規則

1. ローカルを確認する。
2. 未保存ならID種別を明示してAPI取得し、応答の完全一致を検査する。
3. 正規化データと原文・出典を同一トランザクションで保存する。
4. 以降の参照は保存済みを使う。
5. 日本語名・翻訳・効果条件・Master Duelの現行規制の確認状態を混同しない。
6. 取得失敗時は未知に留め、誤った本文で補わない。
