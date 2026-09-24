from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from traffic import (
    HISTORY_MONTHS,
    default_traffic_state,
    entity_rate_mbps,
    entity_total_bytes,
    load_traffic_state,
    save_traffic_state,
    traffic_payload,
    update_traffic,
)


class TrafficTests(unittest.TestCase):
    def test_unit_conversion(self) -> None:
        self.assertEqual(
            entity_total_bytes(
                {"state": "1.5", "attributes": {"unit_of_measurement": "GiB"}}
            ),
            int(1.5 * 1024 ** 3),
        )
        self.assertEqual(
            entity_total_bytes(
                {"state": "2", "attributes": {"unit_of_measurement": "GB"}}
            ),
            2_000_000_000,
        )

    def test_rate_conversion(self) -> None:
        self.assertEqual(
            entity_rate_mbps(
                {"state": "100", "attributes": {"unit_of_measurement": "Mbit/s"}}
            ),
            100.0,
        )
        self.assertEqual(
            entity_rate_mbps(
                {"state": "1", "attributes": {"unit_of_measurement": "MB/s"}}
            ),
            8.0,
        )

    def test_first_sample_is_baseline_not_usage(self) -> None:
        state = default_traffic_state("sensor.down", "sensor.up")
        now = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
        update_traffic(state, 1000, 500, when=now)
        payload = traffic_payload(state, when=now)
        self.assertEqual(payload["download_total_gib"], 0)
        self.assertEqual(payload["upload_total_gib"], 0)

    def test_deltas_survive_counter_reset(self) -> None:
        state = default_traffic_state("sensor.down", "sensor.up")
        now = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
        update_traffic(state, 1000, 500, when=now)
        update_traffic(state, 1600, 900, when=now)
        update_traffic(state, 200, 100, when=now)
        self.assertEqual(state["total"]["download_bytes"], 800)
        self.assertEqual(state["total"]["upload_bytes"], 500)
        self.assertEqual(state["counter_resets"], 1)

    def test_source_change_keeps_history_but_rebaselines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "traffic.json"
            state = default_traffic_state("sensor.old_down", "sensor.old_up")
            now = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
            update_traffic(state, 1000, 500, when=now)
            update_traffic(state, 2000, 1000, when=now)
            save_traffic_state(path, state)

            changed = load_traffic_state(path, "sensor.new_down", "sensor.new_up")
            self.assertEqual(changed["total"]["download_bytes"], 1000)
            self.assertIsNone(changed["last"]["download_bytes"])
            self.assertEqual(changed["source_changes"], 1)

    def test_new_month_rebaselines_cross_boundary_delta(self) -> None:
        state = default_traffic_state("sensor.down", "sensor.up")
        sep = datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc)
        octo = datetime(2026, 10, 1, 0, 1, tzinfo=timezone.utc)
        update_traffic(state, 1000, 500, when=sep)
        update_traffic(state, 5000, 3000, when=octo)
        payload = traffic_payload(state, when=octo)
        self.assertEqual(payload["download_month_gib"], 0)
        self.assertEqual(payload["upload_month_gib"], 0)

    def test_history_is_limited_to_twelve_months(self) -> None:
        state = default_traffic_state("sensor.down", "sensor.up")
        for index in range(14):
            year = 2025 + (index // 12)
            month = (index % 12) + 1
            when = datetime(year, month, 1, tzinfo=timezone.utc)
            update_traffic(state, index * 100 + 100, index * 50 + 50, when=when)
        self.assertLessEqual(len(state["months"]), HISTORY_MONTHS)


if __name__ == "__main__":
    unittest.main()
