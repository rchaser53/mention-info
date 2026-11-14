"""Codexの調査結果を検証し、MEDIUM以上をSlackに通知する。"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


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

    return {
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


def format_message(report: dict[str, Any]) -> str:
    findings = [item for item in report["findings"] if SEVERITIES.index(item["severity"]) >= 1]
    if not findings:
        return ""

    mentions_here = any(item["severity"] in ("HIGH", "CRITICAL") for item in findings)
    lines = [":rotating_light: *サプライチェーン攻撃の調査結果*"]
    if mentions_here:
        lines.append("<!here>")
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


def main() -> int:
    try:
        report = validate_report(json.load(sys.stdin))
        message = format_message(report)
        if not message:
            print("MEDIUM以上の確認済み事案はありません。Slack通知は送信しませんでした。")
            return 0
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        if not webhook_url:
            raise ValueError("MEDIUM以上の事案を通知するには SLACK_WEBHOOK_URL が必要です")
        post_to_slack(webhook_url, message)
        print(f"Slackに{sum(1 for f in report['findings'] if f['severity'] in ('MEDIUM', 'HIGH', 'CRITICAL'))}件の事案を通知しました。")
        return 0
    except (ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
