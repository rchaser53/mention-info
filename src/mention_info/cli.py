"""Codexの調査結果を検証し、HIGH／CRITICALだけをSlackに通知する。"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
NOTIFICATION_SEVERITIES = frozenset(("HIGH", "CRITICAL"))


def validate_report(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict) or not isinstance(report.get("findings"), list):
        raise ValueError("入力は findings 配列を含むJSONオブジェクトにしてください")

    normalized: list[dict[str, str]] = []
    for index, item in enumerate(report["findings"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"finding {index} はオブジェクトで指定してください")
        title = _required_text(item, "title", index)
        severity = _required_text(item, "severity", index).upper()
        if severity not in SEVERITIES:
            raise ValueError(f"finding {index} の severity は LOW / MEDIUM / HIGH / CRITICAL のいずれかにしてください")
        url = _required_text(item, "url", index)
        if not url.startswith(("https://", "http://")):
            raise ValueError(f"finding {index} の url は http または https にしてください")
        summary = _optional_text(item.get("summary"))
        if severity != "LOW" and not summary:
            raise ValueError(f"finding {index} は MEDIUM 以上のため summary が必要です")
        normalized.append({
            "title": title,
            "severity": severity,
            "url": url,
            "summary": summary,
            "published_at": _optional_text(item.get("published_at")),
            "source": _optional_text(item.get("source")),
        })

    audio = report.get("audio", False)
    if not isinstance(audio, bool):
        raise ValueError("audio はbooleanで指定してください")

    return {
        "audio": audio,
        "window_start": _optional_text(report.get("window_start")),
        "window_end": _optional_text(report.get("window_end")),
        "findings": normalized,
    }


def _required_text(item: dict[str, Any], key: str, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"finding {index} に {key} を指定してください")
    return value.strip()


def _optional_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def notification_findings(report: dict[str, Any]) -> list[dict[str, str]]:
    return [item for item in report["findings"] if item["severity"] in NOTIFICATION_SEVERITIES]


def format_message(report: dict[str, Any]) -> str:
    findings = notification_findings(report)
    if not findings:
        return ""

    lines = [":rotating_light: *サプライチェーン攻撃の調査結果*", "<!here>"]
    start, end = report.get("window_start"), report.get("window_end")
    if start or end:
        lines.append(f"対象期間: {start or '不明'} ～ {end or '不明'}")
    for finding in findings:
        lines.append("")
        lines.append(f"*{finding['severity']}* — <{finding['url']}|{finding['title']}>")
        details = [value for value in (finding["published_at"], finding["source"]) if value]
        if details:
            labels = []
            if finding["published_at"]:
                labels.append(f"公表日時: {finding['published_at']}")
            if finding["source"]:
                labels.append(f"情報源: {finding['source']}")
            lines.append(" · ".join(labels))
        lines.append(f"要約: {finding['summary']}")
    return "\n".join(lines)


def validate_notification(notification: Any) -> dict[str, Any]:
    if not isinstance(notification, dict) or not isinstance(notification.get("notify"), bool):
        raise ValueError("入力はbooleanの notify を含むJSONオブジェクトにしてください")
    if not notification["notify"]:
        return {"notify": False, "message": "", "mention": "none"}

    message = notification.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("通知する場合は message を指定してください")
    mention = notification.get("mention", "none")
    if mention not in ("none", "here"):
        raise ValueError("mention は none または here にしてください")
    audio_text = notification.get("audio_text", "")
    if not isinstance(audio_text, str):
        raise ValueError("audio_text は文字列で指定してください")
    return {
        "notify": True,
        "message": message.strip(),
        "mention": mention,
        "audio_text": audio_text.strip(),
    }


def format_notification(notification: dict[str, Any]) -> str:
    if not notification["notify"]:
        return ""
    if notification["mention"] == "here":
        return f"<!here>\n{notification['message']}"
    return notification["message"]


def post_to_slack(webhook_url: str, message: str) -> None:
    payload = json.dumps({"text": message}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"Slack WebhookがHTTP {response.status}を返しました")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Slack WebhookがHTTP {exc.code}を返しました") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Slack Webhookに接続できませんでした: {exc.reason}") from exc


def create_voicevox_audio(text: str) -> Path:
    """Create a Zundamon WAV and attribution sidecar using a local VOICEVOX Engine."""
    engine_url = os.environ.get("VOICEVOX_ENGINE_URL", "http://127.0.0.1:50021").rstrip("/")
    try:
        with urllib.request.urlopen(f"{engine_url}/speakers", timeout=10) as response:
            speakers = json.load(response)
        zundamon = next(item for item in speakers if item.get("name") == "ずんだもん")
        style = next(item for item in zundamon["styles"] if item.get("name") == "ノーマル")
    except (urllib.error.URLError, json.JSONDecodeError, StopIteration, KeyError, TypeError) as exc:
        raise RuntimeError("VOICEVOX Engineからずんだもん（ノーマル）の音声スタイルを取得できません") from exc

    speaker_id = style["id"]
    query = urllib.parse.urlencode({"speaker": speaker_id, "text": text})
    try:
        request = urllib.request.Request(f"{engine_url}/audio_query?{query}", data=b"", method="POST")
        with urllib.request.urlopen(request, timeout=60) as response:
            audio_query = json.load(response)
        synthesis_query = urllib.parse.urlencode({"speaker": speaker_id})
        request = urllib.request.Request(
            f"{engine_url}/synthesis?{synthesis_query}",
            data=json.dumps(audio_query, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            wav_data = response.read()
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError("VOICEVOX Engineで音声を合成できません") from exc

    output_dir = Path(os.environ.get("VOICEVOX_OUTPUT_DIR", "artifacts/audio"))
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    audio_path = output_dir / f"supply-chain-summary-{timestamp}.wav"
    audio_path.write_bytes(wav_data)
    audio_path.with_suffix(".txt").write_text(
        f"VOICEVOX:ずんだもん\n\n{text}\n", encoding="utf-8"
    )
    return audio_path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        audio_text = ""
        if isinstance(payload, dict) and "findings" in payload:
            report = validate_report(payload)
            message = format_message(report)
            selected = notification_findings(report)
            count = len(selected)
            if report["audio"]:
                audio_text = "\n".join(
                    f"{item['severity']}。{item['title']}。{item['summary']}" for item in selected
                )
            no_notification = "HIGH／CRITICALの確認済み事案はありません。Slack通知は送信しませんでした。"
            success_message = f"Slackに{count}件の事案を通知しました。"
        else:
            notification = validate_notification(payload)
            message = format_notification(notification)
            audio_text = notification.get("audio_text", "")
            no_notification = "通知不要と判定されたため、Slack通知は送信しませんでした。"
            success_message = "Slackに通知しました。"
        if not message:
            print(no_notification)
            return 0
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        if not webhook_url:
            raise ValueError("Slackへ通知するには SLACK_WEBHOOK_URL が必要です")
        audio_path = None
        if audio_text:
            audio_path = create_voicevox_audio(audio_text)
        post_to_slack(webhook_url, message)
        print(success_message)
        if audio_path:
            print(f"音声ファイルを作成しました: {audio_path}")
        return 0
    except (ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
