from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from traffic import TRAFFIC_HISTORY_MONTHS, TrafficStore, parse_counter_state


class TrafficTests(unittest.TestCase):
    def test_unit_conversion(self) -> None:
        self.assertEqual(
            parse_counter_state(
                {"state": "1.5", "attributes": {"unit_of_measurement": "GiB"}}
            ),
            int(1.5 * 1024**3),
        )
        self.assertEqual(
            parse_counter_state(
                {"state": "2", "attributes": {"unit_of_measurement": "GB"}}
            ),
            2_000_000_000,
        )

    def test_monthly_delta_and_counter_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TrafficStore.load(Path(tmp) / "traffic.json")
            when = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
            store.update(1_000, 2_000, when)
            store.update(1_500, 2_500, when)
            store.update(100, 200, when)  # source counters reset
            payload = store.payload(
                configured=True,
                available=True,
                download_entity_id="sensor.down",
                upload_entity_id="sensor.up",
                when=when,
            )
            self.assertEqual(store.months["2026-09"]["download_bytes"], 600)
            self.assertEqual(store.months["2026-09"]["upload_bytes"], 700)
            self.assertEqual(payload["history_count"], 1)

    def test_new_month_establishes_new_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TrafficStore.load(Path(tmp) / "traffic.json")
            sep = datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc)
            octo = datetime(2026, 10, 1, 0, 1, tzinfo=timezone.utc)
            store.update(1_000, 1_000, sep)
            store.update(2_000, 3_000, octo)
            self.assertEqual(
                store.months["2026-10"],
                {"download_bytes": 0, "upload_bytes": 0},
            )

    def test_retains_only_twelve_months(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TrafficStore.load(Path(tmp) / "traffic.json")
            for index in range(1, 14):
                year = 2025 + (index // 12)
                month = (index % 12) + 1
                when = datetime(year, month, 15, 12, 0, tzinfo=timezone.utc)
                store.update(index * 1_000, index * 2_000, when)
            self.assertLessEqual(len(store.months), TRAFFIC_HISTORY_MONTHS)


if __name__ == "__main__":
    unittest.main()
