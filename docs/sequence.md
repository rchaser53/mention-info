# 処理シーケンス

この図は、定期実行時に各コンポーネントが担当する処理を示します。

```mermaid
sequenceDiagram
    autonumber
    actor Operator as 運用者
    participant Scheduler as Codexスケジュール
    participant Codex as Codex
    participant Web as 公開情報・Web
    participant Repo as mention-infoリポジトリ
    participant CLI as mention-info CLI
    participant Hook as Slack Incoming Webhook
    participant Slack as Slackチャンネル

    Note over Operator,Repo: 調査指示の管理元は CODEX_SCHEDULE.md。<br/>指示を変えたときはスケジュール設定にも反映する。
    Scheduler->>Codex: 設定時刻に調査タスクを起動
    Codex->>Repo: CODEX_SCHEDULE.mdの指示とCLI仕様を参照
    Codex->>Web: 直近24時間の事案を検索
    Web-->>Codex: 候補記事・アドバイザリ
    Codex->>Web: 一次情報と公表・発生日時を確認
    Web-->>Codex: 根拠情報・日時
    Codex->>Codex: 事案を選別・重複排除・重要度判定<br/>日本語summary付きJSONを作成
    Codex->>CLI: JSONを標準入力で渡して実行
    CLI->>CLI: 入力を検証しMEDIUM以上を抽出
    alt MEDIUM以上の事案がない
        CLI-->>Codex: 通知なしで正常終了
    else MEDIUM以上の事案がある
        opt HIGHまたはCRITICALを含む
            CLI->>CLI: メッセージに <!here> を追加
        end
        CLI->>Hook: 日本語の要約を含むWebhook要求
        Hook->>Slack: メッセージを投稿
        Slack-->>Hook: 投稿結果
        Hook-->>CLI: HTTP応答
        CLI-->>Codex: 投稿成功またはエラーを返す
    end
    Codex-->>Scheduler: 実行サマリーを返す
```

## 担当

- **Codexスケジュール**: 指定時刻に調査タスクを起動します。
- **Codex**: Web調査、一次情報による確認、重複排除、重要度判定、日本語JSONの作成を行います。
- **mention-info CLI**: JSONを検証し、MEDIUM以上の事案を日本語で整形してSlackへ送ります。HIGHまたはCRITICALを含む場合は`<!here>`を付けます。
- **Slack Incoming Webhook / Slack**: CLIから受け取ったメッセージをチャンネルに投稿します。

Slack Webhook URLは`SLACK_WEBHOOK_URL`環境変数からCLIが読み込みます。Codexは値を表示・記録しません。
