# mention-info

Codex が定期的に公開情報を調べ、直近24時間に公表・確認されたサプライチェーン攻撃を評価します。Codex のスケジュールが実行時刻を管理し、このリポジトリは結果の検証と Slack 通知を担当します。GitHub Actions の cron は使いません。

## 処理の流れ

[シーケンス図](docs/sequence.md)に、Codex スケジュール、Codex、公開情報、CLI、Slack の担当とデータの流れを示しています。スケジュール指示文の管理元は [CODEX_SCHEDULE.md](CODEX_SCHEDULE.md) です。スケジュール設定を変更するときは、このファイルの指示をCodex側の設定に反映してください。

## 重要度

- **CRITICAL**: 広範な影響、進行中の侵害、または重要な基盤への深刻な侵入が確認されたもの
- **HIGH**: 悪意あるパッケージ、侵害されたビルド/配布経路、または大きな利用者影響が確認されたもの
- **MEDIUM**: 具体的な攻撃の兆候や限定的な侵害はあるが、影響・悪用の範囲が限定的または未確定のもの
- **LOW**: 影響が小さい、未遂・脆弱性報告にとどまる、またはサプライチェーン攻撃との関連が弱いもの

報道の更新日時と、攻撃が起きた日時を区別します。検索結果の日付だけで判断せず、元のアドバイザリや複数の信頼できる情報源を確認してください。発生・公表時刻が直近24時間と確認できない項目は含めません。確認できる攻撃がなければ空の findings を出力します。

## Slack 通知

MEDIUM 以上の事案を日本語で要約してIncoming Webhookに通知します。HIGHまたはCRITICALが含まれる場合に限り、通知本文の先頭でSlackの`<!here>`を使ってメンションします。LOWのみ、または該当なしの場合は通知しません。MEDIUM以上の各事案には日本語summaryが必要です。

環境変数を設定してください:

```sh
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
```

Codex のスケジュールは、同じ環境変数が見えるローカル環境で実行してください。値をリポジトリ、スケジュールの指示文、ログに書かないでください。

## セットアップ

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

Codex のスケジュールでこのリポジトリをプロジェクトとして選び、毎日実行するよう設定します。スケジュールの実行指示は [CODEX_SCHEDULE.md](CODEX_SCHEDULE.md) を使ってください。GitHub Actions workflow はありません。スケジュールはこのPRのマージ後に有効化してください。

## 手動実行

Codex が調査した結果を、以下のJSON形式で標準入力からCLIに渡します:

```json
{
  "window_start": "2026-01-01T00:00:00Z",
  "window_end": "2026-01-02T00:00:00Z",
  "findings": [
    {
      "title": "Incident title",
      "severity": "HIGH",
      "url": "https://example.com/advisory",
      "published_at": "2026-01-01T12:00:00Z",
      "source": "Publisher",
      "summary": "What happened and why it has this severity."
    }
  ]
}
```

```sh
mention-info-notify < report.json
```

各項目には`title`、`severity`（`LOW`、`MEDIUM`、`HIGH`、`CRITICAL`のいずれか）、HTTP(S)形式の`url`が必要です。MEDIUM以上の項目には日本語の`summary`も必須です。CLIはレポートを検証し、MEDIUM以上を日本語でSlackに投稿します。HIGH/CRITICALが1件以上ある場合だけ`<!here>`を付けます。LOWのみの場合は通知しません。通知対象があるのに`SLACK_WEBHOOK_URL`が未設定の場合や、SlackがWebhook要求を拒否した場合はエラー終了します。
