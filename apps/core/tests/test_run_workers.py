from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

WORKERS = [
    {"name": "alpha", "command": "alpha --limit 5", "interval": 3},
    {"name": "beta", "command": "beta", "interval": 9, "enabled": False},
]


@override_settings(AMATOPAY_WORKERS=WORKERS)
class RunWorkersTests(SimpleTestCase):
    def test_list_shows_every_job_and_runs_nothing(self):
        out = StringIO()
        with patch("apps.core.management.commands.run_workers.call_command") as cc:
            call_command("run_workers", "--list", stdout=out)
        cc.assert_not_called()
        text = out.getvalue()
        self.assertIn("alpha", text)
        self.assertIn("every    3s", text)
        self.assertIn("[off]", text)  # beta disabled

    def test_once_runs_each_enabled_job_with_parsed_args(self):
        out = StringIO()
        with patch("apps.core.management.commands.run_workers.call_command") as cc:
            call_command("run_workers", "--once", stdout=out)
        cc.assert_called_once_with("alpha", "--limit", "5")  # beta skipped (disabled)

    def test_once_reports_failure_but_keeps_going(self):
        out = StringIO()
        with patch(
            "apps.core.management.commands.run_workers.call_command",
            side_effect=RuntimeError("boom"),
        ), self.assertLogs("apps.core.run_workers", level="ERROR"):
            with self.assertRaises(CommandError):
                call_command("run_workers", "--once", stdout=out)
        self.assertIn("failed", out.getvalue())

    def test_only_filters_jobs(self):
        out = StringIO()
        with patch("apps.core.management.commands.run_workers.call_command") as cc:
            call_command("run_workers", "--once", "--only", "alpha", stdout=out)
        cc.assert_called_once()

    def test_unknown_job_name_errors(self):
        with self.assertRaises(CommandError):
            call_command("run_workers", "--only", "ghost")
