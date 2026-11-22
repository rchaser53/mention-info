# 汎用定期処理のシーケンス

スケジュール、タスク固有プロンプト、共通Slack CLIの責務を分けています。

```mermaid
sequenceDiagram
    autonumber
    actor Operator as 運用者
    participant Cron as Codexスケジュール
    participant Codex as Codex
    participant Prompt as ローカル TASK_PROMPT.md
    participant Work as 作業対象・情報源
    participant CLI as mention-info CLI
    participant Voice as VOICEVOX Engine / 音声プレーヤー
    participant Hook as Slack Incoming Webhook
    participant Slack as Slackチャンネル

    Operator->>Cron: 対象プロジェクト・起動時刻・共通ランナーを設定
    Note over Operator,Prompt: 作業内容と通知条件はプロジェクト内のTASK_PROMPT.mdで管理
    Cron->>Codex: 設定時刻にタスクを起動
    Codex->>Prompt: ローカルのタスクプロンプトを読む
    Prompt-->>Codex: 作業手順・通知条件
    Codex->>Work: 指示された定期作業を実行
    Work-->>Codex: 作業結果・根拠情報
    Codex->>Codex: プロンプトの条件に従い通知要否とメンションを判断
    Codex->>CLI: notify/message/mention/audio_textのJSONを渡して実行
    CLI->>CLI: JSONを検証・Slack本文を組み立て
    alt notify=false
        CLI-->>Codex: 通知をスキップして正常終了
    else notify=true, mention=none
        CLI->>Hook: messageをWebhookで送信
        Hook->>Slack: メッセージを投稿
        Slack-->>Hook: 投稿結果
        Hook-->>CLI: HTTP応答
        CLI-->>Codex: 投稿成功またはエラー
    else notify=true, mention=here
        CLI->>CLI: 本文の先頭に <!here> を追加
        alt audio_textあり
            CLI->>Voice: ずんだもん音声を合成
            alt 音声生成成功
                Voice-->>CLI: WAVファイル
                CLI->>Voice: WAVを再生（完了まで待機）
                alt 読み上げ成功
                    Voice-->>CLI: 再生完了
                else 読み上げ失敗
                    Voice-->>CLI: 再生エラー
                    CLI->>CLI: 失敗理由をSlack本文に追記
                end
            else 音声生成失敗
                Voice-->>CLI: 合成エラー
                CLI->>CLI: 失敗理由をSlack本文に追記
            end
        else audio_textなし
            CLI->>CLI: 音声処理をスキップ
        end
        CLI->>Hook: メンション付きmessageをWebhookで送信
        Hook->>Slack: メンション付きメッセージを投稿
        Slack-->>Hook: 投稿結果
        Hook-->>CLI: HTTP応答
        CLI-->>Codex: 投稿成功またはエラー
    end
    Codex-->>Cron: 作業と通知の実行サマリー
```

## 役割

- **Codexスケジュール（cron）**: プロジェクトを指定時刻に起動します。GitHub Actionsは使いません。
- **TASK_PROMPT.md**: タスクごとの作業手順、通知条件、メンション基準を定義します。Gitで管理し、実行時は選択したローカルプロジェクトのファイルを読みます。
- **Codex**: プロンプトに沿って作業し、結果から通知要否を判断して共通JSONを作ります。
- **mention-info CLI**: 共通JSONを検証し、`audio_text`がある場合はVOICEVOXで音声を合成・再生してからSlack Webhookへ中継します。音声処理に失敗しても失敗理由を添えて通知を続けます。タスクの内容や通知しきい値は判断しません。
- **Slack Webhook / Slack**: CLIから受け取ったメッセージをチャンネルに投稿します。

通知JSONは`{"notify": false}`または`{"notify": true, "message": "...", "mention": "none|here", "audio_text": "..."}`です。Webhook URLは`SLACK_WEBHOOK_URL`環境変数から読み込み、値を表示・記録しません。
