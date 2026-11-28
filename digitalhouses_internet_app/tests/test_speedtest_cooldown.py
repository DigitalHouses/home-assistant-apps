"""Technical Speedtest errors must not notify owners or bypass provider limits."""
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_consent import internet_app
from speedtest import default_speedtest_state, load_last_result


class SpeedtestCooldownTests(unittest.TestCase):
    def setUp(self):
        self.app = internet_app.InternetApp.__new__(internet_app.InternetApp)
        self.app.lock = threading.RLock()
        self.app.speedtest_lock = threading.Lock()
        self.app.speedtest = default_speedtest_state()
        self.app.speedtest.update(download_mbps=120, tested_at="2026-11-27T08:00:00+05:00")
        self.app.config = SimpleNamespace(
            router_ip="192.168.1.1", connectivity=SimpleNamespace(timeout_seconds=2),
            speedtest=SimpleNamespace(server_ids=(1, 2), automatic_server_fallback=True,
                                      timeout_seconds=240))
        self.app.log = Mock()
        self.app._publish_state = Mock()
        self.app._event = Mock()
        self.app._refresh_performance = Mock()
        self.when = datetime(2026, 11, 28, tzinfo=timezone.utc)

    def test_rate_limit_stops_fallback_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "speedtest.json"
            with (patch.object(internet_app, "SPEEDTEST_FILE", path),
                  patch.object(internet_app, "now_local", return_value=self.when) as clock,
                  patch.object(internet_app, "sample", return_value=SimpleNamespace(internet_up=True)),
                  patch.object(internet_app, "run_speedtest",
                               side_effect=RuntimeError("Limit reached: Too many requests")) as runner):
                self.app._run_speedtest(source="automatic")
                runner.assert_called_once_with(240, server_id=1)
                self.app._event.assert_not_called()
                self.app._refresh_performance.assert_not_called()
                self.app.speedtest = load_last_result(path)
                self.assertEqual(self.app.speedtest["download_mbps"], 120)
                self.assertEqual(self.app.speedtest["tested_at"], "2026-11-27T08:00:00+05:00")
                self.assertEqual(self.app.speedtest["rate_limit_until"], self.when.timestamp() + 86400)
                self.app._run_speedtest(source="automatic")
                self.app._run_speedtest(source="manual")
                runner.assert_called_once()
                clock.return_value = self.when + timedelta(hours=24)
                self.app._run_speedtest(source="automatic")
                self.assertEqual(runner.call_count, 2)

    def test_other_failures_allow_fallback_without_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.object(internet_app, "SPEEDTEST_FILE", Path(tmp) / "speedtest.json"),
                  patch.object(internet_app, "sample", return_value=SimpleNamespace(internet_up=True)),
                  patch.object(internet_app, "run_speedtest",
                               side_effect=RuntimeError("timeout")) as runner):
                self.app._run_speedtest(source="manual")
                self.assertEqual(runner.call_count, 3)
                self.assertIsNone(self.app.speedtest["rate_limit_until"])
                self.assertEqual(self.app.speedtest["error"], "Speedtest unavailable")
                self.app._event.assert_not_called()
                self.app._refresh_performance.assert_not_called()
