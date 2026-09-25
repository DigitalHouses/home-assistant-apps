from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from recent_results import (
    RECENT_RESULTS_LIMIT,
    append_recent_result,
    build_recent_record,
    load_recent_results,
    recent_results_payload,
    save_recent_results,
)


class RecentResultsTests(unittest.TestCase):
    def test_payload_does_not_change_updated_at_on_publish(self) -> None:
        store = {
            "results": [{"tested_at": "2026-09-23T10:00:00+00:00"}],
            "updated_at": "2026-09-23T10:00:01+00:00",
        }
        first = recent_results_payload(store)
        second = recent_results_payload(store)
        self.assertEqual(first["updated_at"], "2026-09-23T10:00:01+00:00")
        self.assertEqual(second["updated_at"], first["updated_at"])

    def test_record_keeps_thresholds_at_test_time(self) -> None:
        record = build_recent_record(
            {
                "tested_at": "2026-09-23T10:00:00+00:00",
                "download_mbps": 9,
                "upload_mbps": 20,
                "ping_ms": 250,
                "jitter_ms": 1,
                "packet_loss_pct": 0,
                "provider": "ISP",
                "server": "Server",
                "result_url": "https://example/1",
            },
            {
                "minimum_download_mbps": 10,
                "minimum_upload_mbps": 10,
                "maximum_ping_ms": 200,
            },
            {
                "low_download": True,
                "low_upload": False,
                "high_ping": True,
                "performance_problem": True,
            },
        )
        self.assertEqual(record["minimum_download_mbps"], 10)
        self.assertEqual(record["maximum_ping_ms"], 200)
        self.assertTrue(record["performance_problem"])

    def test_newest_first_deduplicated_and_limited(self) -> None:
        store = {"results": [], "updated_at": None}
        for index in range(RECENT_RESULTS_LIMIT + 3):
            record = {
                "tested_at": f"2026-09-23T10:{index:02d}:00+00:00",
                "result_url": f"https://example/{index}",
            }
            store = append_recent_result(store, record)
        self.assertEqual(len(store["results"]), RECENT_RESULTS_LIMIT)
        self.assertEqual(store["results"][0]["result_url"], "https://example/22")
        self.assertIsNotNone(store["updated_at"])

        previous_updated_at = store["updated_at"]
        store = append_recent_result(
            store,
            {
                "tested_at": "2026-09-23T11:00:00+00:00",
                "result_url": "https://example/22",
            },
        )
        self.assertEqual(len(store["results"]), RECENT_RESULTS_LIMIT)
        self.assertEqual(
            store["results"][0]["tested_at"],
            "2026-09-23T11:00:00+00:00",
        )
        self.assertIsNotNone(previous_updated_at)
        self.assertIsNotNone(store["updated_at"])

    def test_legacy_history_backfills_updated_at_from_latest_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recent.json"
            path.write_text(
                '{"results":[{"tested_at":"2026-09-24T19:21:55+05:00"}]}',
                encoding="utf-8",
            )
            loaded = load_recent_results(path)
            self.assertEqual(
                loaded["updated_at"],
                "2026-09-24T19:21:55+05:00",
            )

    def test_round_trip_preserves_updated_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recent.json"
            store = {
                "results": [{"tested_at": "2026-09-23T10:00:00+00:00"}],
                "updated_at": "2026-09-23T10:00:01+00:00",
            }
            save_recent_results(path, store)
            loaded = load_recent_results(path)
            payload = recent_results_payload(loaded)
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["limit"], RECENT_RESULTS_LIMIT)
            self.assertEqual(
                payload["updated_at"],
                "2026-09-23T10:00:01+00:00",
            )


if __name__ == "__main__":
    unittest.main()
