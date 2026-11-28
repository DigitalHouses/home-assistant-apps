"""HA timezone contract: one site source, cache, presentation only."""
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode
from urllib.request import urlopen

from catalog_web import make_server
from compact_web import render, time_text
from discovery_contract import ProductSources
from event_journal import EventJournal
from ha_core import CoreAPI
from ha_timezone import HATimezone, HAFormatter, valid_zone


class TimezoneTests(unittest.TestCase):
    def test_core_config_authority(self):
        api = CoreAPI(token="test")
        with patch.object(api, "_rest", return_value={"time_zone": "Asia/Almaty"}) as request:
            self.assertEqual(api.timezone(), "Asia/Almaty")
            request.assert_called_once_with("config", timeout=5)

    def test_cache_refresh_invalid_and_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "zone"
            resolver = Mock(side_effect=[None, "Invalid/Zone", "Asia/Almaty", OSError(), "Europe/Berlin", None])
            source = HATimezone(resolver, path)
            self.assertEqual(source.snapshot(), ("UTC", True))
            self.assertEqual(source.refresh(), ("UTC", True))
            self.assertEqual(source.refresh(), ("UTC", True))
            self.assertFalse(path.exists())
            self.assertEqual(source.refresh(), ("Asia/Almaty", False))
            self.assertEqual(path.read_text().strip(), "Asia/Almaty")
            self.assertEqual(source.refresh(), ("Asia/Almaty", False))
            self.assertEqual(source.refresh(), ("Europe/Berlin", False))
            self.assertEqual(source.refresh(), ("Europe/Berlin", False))
            self.assertEqual(HATimezone(lambda: None, path).snapshot(), ("Europe/Berlin", False))
            path.write_text("bad timezone")
            self.assertEqual(HATimezone(lambda: None, path).snapshot(), ("UTC", True))
            for bad in ("", "../etc/passwd", "/etc/localtime", 1, None):
                self.assertIsNone(valid_zone(bad))

    def test_dst_and_explicit_utc_fallback(self):
        self.assertEqual(time_text("2026-01-01T12:00:00+00:00", "Europe/Berlin"), "01.01.2026 13:00:00")
        self.assertEqual(time_text("2026-07-01T12:00:00+00:00", "Europe/Berlin"), "01.07.2026 14:00:00")
        self.assertEqual(time_text("2026-07-01T12:00:00+00:00", "Asia/Almaty"), "01.07.2026 17:00:00")
        report = {"last_run": "2026-07-01T12:00:00+00:00"}
        self.assertIn("UTC (fallback)", render({}, report)["status"])
        self.assertIn("Asia/Almaty", render({}, report, timezone_info=("Asia/Almaty", False))["status"])

    def test_runtime_log_uses_ha_not_host(self):
        source = Mock()
        source.snapshot.return_value = ("Asia/Almaty", False)
        formatter = HAFormatter(source)
        record = logging.LogRecord("test", logging.INFO, "", 1, "test", (), None)
        record.created = datetime(2026, 7, 1, 12, tzinfo=timezone.utc).timestamp()
        self.assertEqual(formatter.formatTime(record), "2026-07-01T17:00:00.000+05:00")
        source.snapshot.return_value = ("UTC", True)
        self.assertIn("UTC fallback", formatter.formatTime(record))

    def test_ingress_journal_toast_export_same_timezone_and_utc_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            resolver = Mock(return_value=None)
            source = HATimezone(resolver, path / "zone")
            journal = EventJournal(path / "journal.db")
            journal.backend.clock = lambda: datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
            journal.backend.start("0.6.9")
            journal.record("sync_result", level="success", notify=True, views=1, packages=0, dashboards=0)
            report = {"last_run": "2026-07-01T12:00:00+00:00"}
            server = make_server(ProductSources(), port=0, auto_status=lambda: report, journal=journal,
                                 timezone_source=source.snapshot)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            def get(path):
                with urlopen(base + path, timeout=3) as response:
                    return json.load(response)
            try:
                first = get("/api/log")
                self.assertIn("UTC (fallback)", first["product_name"])
                self.assertIn("12:00:00", first["rows"][-1]["local_time"])
                saved = journal.backend.snapshot()["rows"]
                self.assertIn("UTC (fallback)", get("/api/sync/status")["fragments"]["status"])
                resolver.return_value = "Asia/Almaty"
                source.refresh()
                query = urlencode({"after":first["newest"], "generation":first["generation"]})
                second = get("/api/log?" + query)
                self.assertNotEqual(first["generation"], second["generation"])
                self.assertEqual(len(second["rows"]), 2)
                self.assertIn("17:00:00", second["rows"][-1]["local_time"])
                self.assertIn("Asia/Almaty", second["product_name"])
                query = urlencode({"after":second["newest"], "generation":second["generation"]})
                self.assertEqual(get("/api/log?" + query)["rows"], [])
                toast = get("/api/log/toasts?after=0")["rows"][0]
                self.assertIn("17:00:00 Asia/Almaty", toast["local_time"])
                self.assertEqual(toast["ts"], saved[-1]["ts"])
                self.assertIn("17:00:00", get("/api/sync/status")["fragments"]["status"])
                with urlopen(base + "/api/log/export?lang=en") as response:
                    self.assertIn("2026-07-01_17-00-00.log", response.headers["Content-Disposition"])
                    self.assertIn(b"2026-07-01T17:00:00.000+05:00", response.read())
                resolver.return_value = "Europe/Berlin"
                source.refresh()
                self.assertIn("14:00:00", get("/api/log?" + query)["rows"][-1]["local_time"])
                self.assertEqual(journal.backend.snapshot()["rows"], saved)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                journal.backend.close()
