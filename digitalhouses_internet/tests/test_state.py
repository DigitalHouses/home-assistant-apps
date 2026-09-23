from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from state import OutageTracker, duration_text


class OutageTests(unittest.TestCase):
    def test_duration_text(self) -> None:
        self.assertEqual(duration_text(65), "01:05")
        self.assertEqual(duration_text(3661), "1:01:01")

    def test_current_outage_is_visible_and_then_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outages.json"
            tracker = OutageTracker(
                path=path,
                month="2026-09",
                outages=[],
                active_from=None,
            )
            start = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
            end = datetime(2026, 9, 23, 10, 2, 5, tzinfo=timezone.utc)

            self.assertTrue(tracker.start(start))
            payload = tracker.payload(end)
            self.assertEqual(payload["state"], 1)
            self.assertIsNone(payload["outages"][0]["to"])
            self.assertEqual(payload["outages"][0]["duration_seconds"], 125)

            record = tracker.recover(end)
            self.assertIsNotNone(record)
            self.assertEqual(record["duration"], "02:05")
            self.assertEqual(tracker.payload(end)["state"], 1)


if __name__ == "__main__":
    unittest.main()
