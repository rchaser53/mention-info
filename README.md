# mention-info

ローカルのCodexスケジュールから任意の定期タスクを実行し、タスクごとの指示に従って必要な場合だけSlackへ通知するための共通ランナーとCLIです。スケジュールが起動時刻を管理し、作業内容・通知条件はプロジェクト内の`TASK_PROMPT.md`、Slack通知の中継はこのCLIが担当します。GitHub Actionsのcronは使いません。

## 処理の流れ

[シーケンス図](docs/sequence.md)に、Codexスケジュール、Codex、ローカルプロンプト、CLI、Slackの担当とデータの流れを示しています。スケジュールに設定する共通ランナー指示は[CODEX_SCHEDULE.md](CODEX_SCHEDULE.md)、タスク固有の作業内容と通知条件は[TASK_PROMPT.md](TASK_PROMPT.md)で管理します。

## 共通の通知形式

各タスクのプロンプトが通知するかどうかとメンションの要否を決めます。通知する場合は次のJSONをCLIへ渡します:

```json
{
  "notify": true,
  "message": "Slackに投稿する本文",
  "mention": "here"
}
```

`mention`は`none`または`here`です。省略時は`none`です。通知しない場合は`{"notify": false}`を渡します。CLIは`here`の場合に`<!here>`を本文の先頭に付けて投稿します。

通知JSONに`audio_text`がある場合、CLIはSlack送信前にVOICEVOX Engineでずんだもん（ノーマル）のWAVを合成して再生します。WAVを`artifacts/audio/`へ保存し、同名の`.txt`ファイルに`VOICEVOX:ずんだもん`のクレジットと読み上げ文を記録します。EngineのURLは`VOICEVOX_ENGINE_URL`で変更でき、既定値は`http://127.0.0.1:50021`です。音声の生成または再生に失敗した場合は、失敗理由をSlack本文に追記して通知を続けます。音声を使うには、通知実行時にVOICEVOX Engineと音声プレーヤーが利用可能である必要があります。

環境変数を設定してください:

```sh
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
```

値をプロンプト、リポジトリ、実行ログに書かないでください。

## サプライチェーン攻撃のサンプルタスク

このリポジトリの`TASK_PROMPT.md`は、製作者・メンテナーのアカウントや公開認証情報の侵害などで、既存の正規パッケージが攻撃者に奪取され、悪意あるバージョンが配布された事案だけを調査します。新規の悪意あるパッケージや、乗っ取りを伴わないマルウェア混入などは対象外です。対象となる事案のうちMEDIUM以上を通知し、HIGH/CRITICALを含む場合だけ`here`メンションします。

## USD/JPY急変監視のサンプル

[`tasks/usdjpy/TASK_PROMPT.md`](tasks/usdjpy/TASK_PROMPT.md)に、価格の参照時間と急変しきい値を変更できる監視プロンプトを置いています。[`tasks/usdjpy/CODEX_SCHEDULE.md`](tasks/usdjpy/CODEX_SCHEDULE.md)を使い、Codexスケジュールを平日毎正時に設定します。既定の急変しきい値は0.30%で、超えた場合だけ`here`メンション付きSlack通知を出します。

## 日本株カップ・アンド・ハンドル監視

[`tasks/japanese-cup-handle/TASK_PROMPT.md`](tasks/japanese-cup-handle/TASK_PROMPT.md)に、Yahoo!ファイナンスの週足・2年チャートを使った日本株候補スクリーニングを追加しています。1時間ごとに最大100銘柄を順番に処理し、進捗と重複通知抑制情報を`state.json`に保存します。新しい候補が見つかった場合だけSlackに通知します。Codexのローカルスケジュールには[`tasks/japanese-cup-handle/CODEX_SCHEDULE.md`](tasks/japanese-cup-handle/CODEX_SCHEDULE.md)を設定してください。

### 実行

日本株チャート監視を手動で1回実行するには、対象プロジェクトの仮想環境で次を実行します。1時間ごとのローカルスケジュールには[`tasks/japanese-cup-handle/CODEX_SCHEDULE.md`](tasks/japanese-cup-handle/CODEX_SCHEDULE.md)を設定してください。

```sh
mention-info-screen-cup-handle
```

1回あたり最大100銘柄を処理します。カーソルは`tasks/japanese-cup-handle/state.json`に保存されます。このファイルは実行時状態のためGit管理対象外です。候補通知には`SLACK_WEBHOOK_URL`が必要です。

## セットアップ

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

Codexのローカルスケジュールで対象プロジェクトを選び、[CODEX_SCHEDULE.md](CODEX_SCHEDULE.md)の共通ランナー指示を設定します。スケジュールの起動時にローカルの`TASK_PROMPT.md`を読み、指示どおりに処理します。別の処理を定期実行する場合は、対象プロジェクトにタスク用`TASK_PROMPT.md`を置き、作業と通知条件を記述します。GitHub Actions workflowは使いません。

スケジュール実行環境から`mention-info-notify`コマンドと`SLACK_WEBHOOK_URL`を利用できるように設定してください。

## 手動実行

汎用形式のJSONを標準入力からCLIに渡します:

```json
{
  "notify": true,
  "message": "定期処理の結果をここに記載します。",
  "mention": "none"
}
```

通知不要の場合は`{"notify": false}`を渡します。

```sh
mention-info-notify < report.json
```

CLIは`SLACK_WEBHOOK_URL`が設定されていない場合や、SlackがWebhook要求を拒否した場合にエラー終了します。以前のサプライチェーン専用形式（`findings`配列）も後方互換のため受け付けます。この形式ではMEDIUM以上を投稿し、HIGH/CRITICALを含む場合に`<!here>`を付けます。
