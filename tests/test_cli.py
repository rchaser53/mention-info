import io
import json
import os
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from mention_info import cli


def finding(severity):
    return {"title": f"事案{severity}", "severity": severity,
            "url": f"https://example.com/{severity}", "summary": f"要約{severity}"}


class NotificationPolicyTests(unittest.TestCase):
    def run_cli(self, payload, webhook=False):
        output, errors = io.StringIO(), io.StringIO()
        env = {"SLACK_WEBHOOK_URL": "https://example.invalid/test"} if webhook else {}
        with patch.dict(os.environ, env, clear=True), \
                patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                patch.object(cli, "post_to_slack") as post, \
                patch.object(cli, "create_voicevox_audio", return_value=Path("test.wav")) as audio, \
                redirect_stdout(output), redirect_stderr(errors):
            code = cli.main()
        return code, output.getvalue(), errors.getvalue(), post, audio

    def test_non_notifiable_reports_do_not_require_webhook_or_call_services(self):
        for levels in ([], ["LOW"], ["MEDIUM"], ["LOW", "MEDIUM"]):
            with self.subTest(levels=levels):
                code, out, err, post, audio = self.run_cli(
                    {"findings": [finding(s) for s in levels], "audio": True})
                self.assertEqual(code, 0)
                self.assertIn("送信しませんでした", out)
                self.assertEqual(err, "")
                post.assert_not_called()
                audio.assert_not_called()

    def test_each_notifiable_severity_sends_with_here(self):
        for level in ("HIGH", "CRITICAL"):
            with self.subTest(level=level):
                code, out, err, post, audio = self.run_cli(
                    {"findings": [finding(level)]}, webhook=True)
                self.assertEqual(code, 0)
                self.assertIn("Slackに1件", out)
                self.assertEqual(err, "")
                self.assertIn("<!here>", post.call_args.args[1])
                self.assertIn(f"事案{level}", post.call_args.args[1])
                audio.assert_not_called()

    def test_mixed_report_excludes_lower_severities_from_text_audio_and_count(self):
        code, out, err, post, audio = self.run_cli({
            "window_start": "2026-01-01T00:00:00Z",
            "window_end": "2026-01-02T00:00:00Z",
            "findings": [finding(s) for s in cli.SEVERITIES], "audio": True,
            "notify": False, "mention": "none", "message": "事案MEDIUM",
            "audio_text": "事案LOW",
        }, webhook=True)
        self.assertEqual(code, 0)
        self.assertIn("Slackに2件", out)
        self.assertEqual(err, "")
        message = post.call_args.args[1]
        spoken = audio.call_args.args[0]
        self.assertIn("2026-01-01T00:00:00Z", message)
        self.assertEqual(message.count("<!here>"), 1)
        for level in cli.SEVERITIES:
            for content in (message, spoken):
                if level in ("HIGH", "CRITICAL"):
                    self.assertIn(f"事案{level}", content)
                else:
                    self.assertNotIn(f"事案{level}", content)

    def test_all_findings_are_validated_even_when_not_notifiable(self):
        for bad in ({**finding("MEDIUM"), "summary": ""}, finding("UNKNOWN")):
            with self.subTest(bad=bad):
                code, out, err, post, audio = self.run_cli(
                    {"findings": [finding("HIGH"), bad]}, webhook=True)
                self.assertEqual(code, 2)
                post.assert_not_called()
                audio.assert_not_called()

    def test_high_requires_webhook(self):
        code, out, err, post, audio = self.run_cli({"findings": [finding("HIGH")]})
        self.assertEqual(code, 2)
        self.assertIn("SLACK_WEBHOOK_URL", err)
        post.assert_not_called()

    def test_audio_failure_prevents_slack_delivery(self):
        with patch.object(cli, "create_voicevox_audio", side_effect=RuntimeError("音声合成失敗")), \
                patch.object(cli, "post_to_slack") as post, \
                patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://example.invalid/test"}), \
                patch("sys.stdin", io.StringIO(json.dumps({"findings": [finding("HIGH")], "audio": True}))), \
                redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(), 2)
            post.assert_not_called()

    def test_generic_notification_remains_compatible(self):
        code, out, err, post, audio = self.run_cli(
            {"notify": True, "message": "他タスク", "mention": "none", "audio_text": "読み上げ"}, webhook=True)
        self.assertEqual(code, 0)
        self.assertEqual(post.call_args.args[1], "他タスク")
        audio.assert_called_once_with("読み上げ")
        code, out, err, post, audio = self.run_cli({"notify": False})
        self.assertEqual(code, 0)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
