# APIキーを使わないChatGPT接続

Sign in with ChatGPTの公式ローカルアプリ向けフローを実装しています。通常のAPIキーは不要です。対象アカウントでプラン利用の権限を許可した場合だけ、公開Responses APIにOAuth認証で問い合わせます。ChatGPT/Codexの既存認証ファイルを読み出したり、backend-apiを使ったりしません。

## ログインとモデル選択

advisorフォルダーのPowerShellから実行してください。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m master_duel_advisor chatgpt-login
.\.venv\Scripts\python.exe -X utf8 -m master_duel_advisor chatgpt-status
.\.venv\Scripts\python.exe -X utf8 -m master_duel_advisor chatgpt-models
```

ログインはブラウザで本人が行います。アプリ登録名はMaster Duel Local Advisorです。ブラウザで登録とプラン利用の許可を確認してください。ログインだけ成立してplan_enabledがfalseの場合は、プラン利用を許可して同じ登録を再認証する必要があります。認証中はコマンドを終了しないでください。既定300秒で期限切れになります。ブラウザを自動起動したくない場合は `chatgpt-login --no-browser` で表示されたローカル開始URLを開きます。

一覧に表示されたモデルのslugを選び、既存のrunまたはagent-loopコマンドに次を追加します。

```powershell
--chatgpt --chatgpt-model MODEL_SLUG --llm-max-calls 5 --llm-timeout 10 --llm-cooldown 30
```

MODEL_SLUGは実際の一覧から置き換えます。通常のローカル処理では通信しません。表示上の曖昧な複数候補やローカル判断ができない局面だけ非同期で構造化GameStateを送ります。現在の認識候補と一致した応答だけを利用し、確認UI・演出・入力結果の確認中は外部戦略に切り替えません。プラン枠の上限・権限失効・通信失敗・未完了のストリームでは操作候補を採用しません。APIキー課金への自動切替はありません。

返答はJSON Schemaで制約し、最新盤面と候補に照合します。reasonは表示用です。画像やウィンドウ画像は送信せず、未公開カードは未知のまま送ります。呼出し上限は要求数で、失敗も含みます。トークン数やプランの残量をローカルで正確に推定した値ではありません。利用枠はChatGPT SettingsのUsageで確認します。

## アカウントと保存

```powershell
.\.venv\Scripts\python.exe -X utf8 -m master_duel_advisor chatgpt-login --new
.\.venv\Scripts\python.exe -X utf8 -m master_duel_advisor chatgpt-select PROFILE_ID
.\.venv\Scripts\python.exe -X utf8 -m master_duel_advisor chatgpt-logout
```

PROFILE_IDはstatusの保存済み登録IDです。登録とワークスペースを分けて保持します。サインアウト後も登録IDとhost IDを保つため、同じ接続を再認証できます。アカウントを切り替えたら実行中のループを停止し、モデル一覧を取得してから起動し直してください。

既定の保存先は実行ディレクトリの `.chatgpt/` です。Windowsではトークンを現在のWindowsユーザーのDPAPIで暗号化し、他ユーザーや別PCでは復号できません。Linuxでは専用ディレクトリ0700・ファイル0600です。保存先を変える時は認証コマンドの `--storage` と実行コマンドの `--chatgpt-storage` を揃えます。署名検証、issuer/audience/期限/nonce検査、PKCE、state検査、原子的保存、同一ストアのプロセス間更新ロックを実装しています。異なるストアに同じ更新トークンを複製しないでください。

署名検証にはPyJWTとcryptographyを採用し、HTTP、PKCE、ループバック受信はPython標準ライブラリで実装しました。requirements.lockに依存を固定しています。ログ・画面表示には認証トークンや認証コードを出しません。

## 検証と限界

Unit Testは公開鍵署名、取り違え・nonce/state・期限・権限検査、更新トークンのローテーション、暗号化保存、SSEのcompleted必須、モデル照合、曖昧な候補での非同期判断を確認します。Windows DPAPIテストは通常のWindowsユーザー環境が必要です。サンドボックスの一時フォルダーを再利用せず、例えば `python -X utf8 -m pytest -q --basetemp=artifacts/tests-user -p no:cacheprovider` で実行できます。

`scripts/validate_chatgpt_endpoints.py` で公式discoveryと公開署名鍵への実通信を確認済みです。2026-10-04に本人ログイン、プラン利用権限、モデル一覧取得、gpt-5.6-lunaによるJSON Schema応答を実通信で確認しました。接続確認1回はモデル一覧を含め約4.2秒で、ゲーム入力は行っていません。実環境ではContent-TypeのないSSEが返ったため、本文フレーミングとcompletedイベントの検査を維持して対応しました。選べるモデルはアカウントと時期で変わります。

既存のrun/agent-loopに `--chatgpt --chatgpt-model gpt-5.6-luna` を追加して、この接続を利用できます。再検証は `python -X utf8 scripts/validate_chatgpt_inference.py --model gpt-5.6-luna` で行います。認証トークンを出力せず、接続確認結果はartifacts/chatgpt-inference-validation.jsonへ保存します。

公式仕様:

- [ローカル登録と認証](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [モデル一覧とストリーム推論](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [セッション管理](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
- [プレビューの制約](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
