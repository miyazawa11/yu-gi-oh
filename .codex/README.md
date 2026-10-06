# エージェント設定

| 担当 | 設定 | モデル | Reasoning |
| --- | --- | --- | --- |
| Coordinator（親） | config.toml | gpt-6-astra | medium |
| Implementer | agents/implementer.toml | gpt-6.1-sol | medium |
| Implementer（難しい実装） | agents/implementer_high.toml | gpt-6.1-sol | high |
| Real Device Tester | agents/real_device_tester.toml | gpt-6.1-sol | medium |
| Researcher | agents/researcher.toml | gpt-6.1-sol | low |

Coordinator は親セッションの役割です。別のCoordinator子エージェントは起動しません。
同時に開く子エージェントは最大3つです。Implementerの通常用とHigh用は同じ役割の代替設定であり、同時に編集させません。
難易度の判断とHigh版への切り替えはCoordinatorの運用ルールです。自動難易度判定プログラムを追加したものではありません。

## 利用方法

このプロジェクトを信頼済みのローカルプロジェクトとして開き、新しいセッションで使用します。
アプリでモデルを明示選択している場合は、親を GPT-6 Astra / Medium に合わせてください。
CLIで親モデルを明示して開始する場合、プロジェクトルートで実行します。

    codex -m gpt-6-astra -c model_reasoning_effort='"medium"'

依頼例：

> researcher で現状を調査し、implementer で実装、real_device_tester で実機検証してください。難しい実装は implementer_high に切り替えてください。

カスタム役割名を選択できるクライアントでは該当名を指定します。
現在のツールが役割名を受け取れない場合、Coordinator は該当TOMLを読み、
起動時の model / reasoning_effort を明示し、developer_instructions の内容を委任指示として渡します。
モデルを上書きする際に全履歴forkが使えないツールでは、必要な背景・パス・受入条件を明示して委任します。

ファイル作成だけでは、すでに動いている親・子エージェントのモデルは変更されません。
既存の子は作業停止と引き継ぎを確認してから、新設定で起動し直します。
この設定は権限の緩和や承認の省略を指定しません。Researcherは読み取り専用を指定しています。
セッションの明示設定や管理ポリシーが優先される場合があるため、起動した役割とモデルを確認してください。

公式仕様：https://learn.chatgpt.com/docs/agent-configuration/subagents