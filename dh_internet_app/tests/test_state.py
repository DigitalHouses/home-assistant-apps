from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from state import (
    OutageTracker,
    RecoveryRuntimeState,
    duration_text,
    load_discovery_components,
    save_discovery_components,
)


class OutageTests(unittest.TestCase):
    def test_duration_text(self) -> None:
        self.assertEqual(duration_text(65), "01:05")
        self.assertEqual(duration_text(3661), "1:01:01")

    def test_discovery_component_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "discovery.json"
            self.assertEqual(load_discovery_components(path), set())

            expected = {
                "router_wan_status",
                "traffic_download_total",
            }
            save_discovery_components(path, expected)

            self.assertEqual(
                load_discovery_components(path),
                expected,
            )

    def test_recovery_runtime_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recovery.json"
            deadline = datetime(
                2026, 9, 23, 10, 15, tzinfo=timezone.utc
            )
            state = RecoveryRuntimeState(
                stopped=True,
                cycle=3,
                cooldown_until=deadline,
            )
            state.save(path)

            loaded = RecoveryRuntimeState.load(path)

            self.assertTrue(loaded.stopped)
            self.assertEqual(loaded.cycle, 3)
            self.assertEqual(loaded.cooldown_until, deadline)
            self.assertEqual(
                loaded.cooldown_remaining(
                    datetime(2026, 9, 23, 10, 14, 30, tzinfo=timezone.utc)
                ),
                30,
            )

    def test_recovery_runtime_reset(self) -> None:
        state = RecoveryRuntimeState(
            stopped=True,
            cycle=3,
            cooldown_until=datetime(
                2026, 9, 23, 10, 15, tzinfo=timezone.utc
            ),
        )
        state.reset()
        self.assertFalse(state.stopped)
        self.assertEqual(state.cycle, 0)
        self.assertIsNone(state.cooldown_until)

    def test_pending_outage_round_trip_preserves_first_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outages.json"
            tracker = OutageTracker(
                path=path,
                month="2026-09",
                outages=[],
                active_from=None,
            )
            first = datetime(2026, 9, 24, 20, 34, 34, tzinfo=timezone.utc)
            second = datetime(2026, 9, 24, 20, 34, 44, tzinfo=timezone.utc)

            self.assertEqual(tracker.note_pending_failure(first), 1)
            self.assertEqual(tracker.note_pending_failure(second), 2)

            with patch("state.now_local", return_value=second):
                loaded = OutageTracker.load(path)

            self.assertEqual(loaded.pending_from, first)
            self.assertEqual(loaded.pending_attempts, 2)
            self.assertIsNone(loaded.active_from)

    def test_confirmed_outage_starts_at_first_failed_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outages.json"
            tracker = OutageTracker(
                path=path,
                month="2026-09",
                outages=[],
                active_from=None,
            )
            first = datetime(2026, 9, 24, 20, 34, 34, tzinfo=timezone.utc)
            second = datetime(2026, 9, 24, 20, 34, 44, tzinfo=timezone.utc)
            third = datetime(2026, 9, 24, 20, 34, 54, tzinfo=timezone.utc)
            recovered = datetime(2026, 9, 24, 20, 35, 46, tzinfo=timezone.utc)

            tracker.note_pending_failure(first)
            tracker.note_pending_failure(second)
            tracker.note_pending_failure(third)
            self.assertTrue(tracker.confirm_pending(third))
            self.assertEqual(tracker.active_from, first)
            self.assertIsNone(tracker.pending_from)
            self.assertEqual(tracker.pending_attempts, 0)

            record = tracker.recover(recovered)
            self.assertIsNotNone(record)
            self.assertEqual(record["from"], "2026-09-24T20:34:34+00:00")
            self.assertEqual(record["duration_seconds"], 72)

    def test_pending_outage_is_cleared_if_connection_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outages.json"
            tracker = OutageTracker(
                path=path,
                month="2026-09",
                outages=[],
                active_from=None,
            )
            first = datetime(2026, 9, 24, 20, 34, 34, tzinfo=timezone.utc)

            tracker.note_pending_failure(first)
            tracker.clear_pending()

            loaded = OutageTracker.load(path)
            self.assertIsNone(loaded.pending_from)
            self.assertEqual(loaded.pending_attempts, 0)
            self.assertIsNone(loaded.active_from)
            self.assertEqual(loaded.outages, [])

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

    def test_active_outage_rolls_to_exact_month_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outages.json"
            tracker = OutageTracker(
                path=path,
                month="2026-08",
                outages=[],
                active_from=datetime(
                    2026, 8, 31, 23, 55, tzinfo=timezone.utc
                ),
            )
            now = datetime(2026, 9, 1, 0, 0, 10, tzinfo=timezone.utc)

            payload = tracker.payload(now)

            self.assertEqual(tracker.month, "2026-09")
            self.assertEqual(
                tracker.active_from,
                datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc),
            )
            self.assertEqual(payload["offline_seconds"], 10)

    def test_load_preserves_active_outage_across_month_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outages.json"
            path.write_text(
                json.dumps(
                    {
                        "month": "2026-08",
                        "outages": [],
                        "active_from": "2026-08-31T23:55:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            now = datetime(2026, 9, 1, 0, 0, 10, tzinfo=timezone.utc)
            with patch("state.now_local", return_value=now):
                tracker = OutageTracker.load(path)

            self.assertEqual(tracker.month, "2026-09")
            self.assertEqual(
                tracker.active_from,
                datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc),
            )
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["month"], "2026-09")
            self.assertEqual(
                persisted["active_from"],
                "2026-09-01T00:00:00+00:00",
            )

    def test_month_availability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outages.json"
            tracker = OutageTracker(
                path=path,
                month="2026-09",
                outages=[
                    {
                        "from": "2026-09-01T00:00:00+00:00",
                        "to": "2026-09-01T01:00:00+00:00",
                        "duration_seconds": 3600,
                        "duration": "1:00:00",
                    }
                ],
                active_from=None,
            )
            now = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
            payload = tracker.payload(now)
            self.assertEqual(payload["elapsed_seconds"], 86400)
            self.assertEqual(payload["offline_seconds"], 3600)
            self.assertEqual(payload["online_seconds"], 82800)
            self.assertAlmostEqual(payload["availability_percent"], 95.833, places=3)


if __name__ == "__main__":
    unittest.main()
