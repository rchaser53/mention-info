"""Validate Codex research results and notify Slack about HIGH+ findings."""

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
        raise ValueError("Input must be a JSON object with a findings array")

    normalized: list[dict[str, str]] = []
    for index, item in enumerate(report["findings"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"finding {index} must be an object")
        title = _required_text(item, "title", index)
        severity = _required_text(item, "severity", index).upper()
        if severity not in SEVERITIES:
            raise ValueError(f"finding {index} severity must be LOW, MEDIUM, HIGH, or CRITICAL")
        url = _required_text(item, "url", index)
        if not url.startswith(("https://", "http://")):
            raise ValueError(f"finding {index} url must be http(s)")
        normalized.append({
            "title": title,
            "severity": severity,
            "url": url,
            "summary": _optional_text(item.get("summary")),
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
        raise ValueError(f"finding {index} requires a non-empty {key}")
    return value.strip()


def _optional_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def format_message(report: dict[str, Any]) -> str:
    findings = [item for item in report["findings"] if SEVERITIES.index(item["severity"]) >= 2]
    if not findings:
        return ""

    lines = [":rotating_light: *Supply-chain attack report (HIGH+)*"]
    start, end = report.get("window_start"), report.get("window_end")
    if start or end:
        lines.append(f"Window: {start or 'unknown'} → {end or 'unknown'}")
    for finding in findings:
        lines.append("")
        lines.append(f"*{finding['severity']}* — <{finding['url']}|{finding['title']}>")
        details = [value for value in (finding["published_at"], finding["source"]) if value]
        if details:
            lines.append(" · ".join(details))
        if finding["summary"]:
            lines.append(finding["summary"])
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
                raise RuntimeError(f"Slack webhook returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Slack webhook returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Slack webhook: {exc.reason}") from exc


def main() -> int:
    try:
        report = validate_report(json.load(sys.stdin))
        message = format_message(report)
        if not message:
            print("No HIGH or CRITICAL findings; no Slack notification sent.")
            return 0
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        if not webhook_url:
            raise ValueError("SLACK_WEBHOOK_URL is required when HIGH or CRITICAL findings exist")
        post_to_slack(webhook_url, message)
        print(f"Sent Slack notification for {sum(1 for f in report['findings'] if f['severity'] in ('HIGH', 'CRITICAL'))} finding(s).")
        return 0
    except (ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
