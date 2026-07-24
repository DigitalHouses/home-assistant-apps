from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from core import (  # noqa: E402
    append_recent_result,
    atomic_write_json,
    build_recent_record,
    build_success_state,
    default_recent_results,
    default_state,
    evaluate_performance,
    is_result_fresh,
    load_json,
    migrate_recent_results,
    normalize_thresholds,
    parse_server_list,
    recent_results_payload,
    update_runtime_status,
)


THRESHOLDS = {
    "minimum_download_mbps": 10,
    "minimum_upload_mbps": 10,
    "maximum_ping_ms": 200,
}


def successful_state(
    *,
    download: float = 50,
    upload: float = 40,
    ping: float = 20,
    timestamp: str = "2026-07-24T07:00:00Z",
) -> dict:
    state = default_state()
    state.update(
        {
            "status": "Success",
            "download_mbps": download,
            "upload_mbps": upload,
            "ping_ms": ping,
            "jitter_ms": 1.5,
            "packet_loss": None,
            "provider": "Example ISP",
            "external_ip": "203.0.113.10",
            "server": "OBIT — Almaty, Kazakhstan",
            "server_id": "56519",
            "result_url": "https://www.speedtest.net/result/c/example",
            "last_success": timestamp,
            "last_attempt": timestamp,
        }
    )
    return state


class ThresholdEvaluationTests(unittest.TestCase):
    def test_download_below_threshold_is_problem(self) -> None:
        result = evaluate_performance(
            successful_state(download=9.9),
            THRESHOLDS,
            available=True,
        )
        self.assertEqual(result["low_download"]["state"], "ON")

    def test_download_equal_threshold_is_normal(self) -> None:
        result = evaluate_performance(
            successful_state(download=10),
            THRESHOLDS,
            available=True,
        )
        self.assertEqual(result["low_download"]["state"], "OFF")

    def test_upload_below_threshold_is_problem(self) -> None:
        result = evaluate_performance(
            successful_state(upload=9),
            THRESHOLDS,
            available=True,
        )
        self.assertEqual(result["low_upload"]["state"], "ON")

    def test_upload_equal_threshold_is_normal(self) -> None:
        result = evaluate_performance(
            successful_state(upload=10),
            THRESHOLDS,
            available=True,
        )
        self.assertEqual(result["low_upload"]["state"], "OFF")

    def test_ping_above_threshold_is_problem(self) -> None:
        result = evaluate_performance(
            successful_state(ping=201),
            THRESHOLDS,
            available=True,
        )
        self.assertEqual(result["high_ping"]["state"], "ON")

    def test_ping_equal_threshold_is_normal(self) -> None:
        result = evaluate_performance(
            successful_state(ping=200),
            THRESHOLDS,
            available=True,
        )
        self.assertEqual(result["high_ping"]["state"], "OFF")

    def test_aggregate_problem_uses_or_logic(self) -> None:
        result = evaluate_performance(
            successful_state(download=5, upload=20, ping=20),
            THRESHOLDS,
            available=True,
        )
        self.assertEqual(result["performance_problem"]["state"], "ON")
        attrs = result["performance_problem"]["attributes"]
        self.assertTrue(attrs["low_download"])
        self.assertFalse(attrs["low_upload"])
        self.assertFalse(attrs["high_ping"])

    def test_low_speed_is_download_or_upload(self) -> None:
        result = evaluate_performance(
            successful_state(download=20, upload=5, ping=20),
            THRESHOLDS,
            available=True,
        )
        attrs = result["performance_problem"]["attributes"]
        self.assertTrue(attrs["low_speed"])
        self.assertEqual(attrs["problem_reasons"], ["low_upload"])

    def test_threshold_change_recalculates_last_measurement(self) -> None:
        state = successful_state(download=34)
        old_result = evaluate_performance(
            state,
            {**THRESHOLDS, "minimum_download_mbps": 30},
            available=True,
        )
        new_result = evaluate_performance(
            state,
            {**THRESHOLDS, "minimum_download_mbps": 50},
            available=True,
        )
        self.assertEqual(old_result["low_download"]["state"], "OFF")
        self.assertEqual(new_result["low_download"]["state"], "ON")

    def test_attributes_contain_value_threshold_and_difference(self) -> None:
        result = evaluate_performance(
            successful_state(download=34),
            {**THRESHOLDS, "minimum_download_mbps": 50},
            available=True,
            evaluated_at="2026-07-24T08:00:00Z",
        )
        attrs = result["low_download"]["attributes"]
        self.assertEqual(attrs["current_value"], 34)
        self.assertEqual(attrs["threshold"], 50)
        self.assertEqual(attrs["comparison"], "less_than")
        self.assertEqual(attrs["difference"], -16)
        self.assertEqual(attrs["result_timestamp"], "2026-07-24T07:00:00Z")
        self.assertEqual(attrs["evaluated_at"], "2026-07-24T08:00:00Z")


class RecentResultsTests(unittest.TestCase):
    def test_record_stores_thresholds_at_test_time(self) -> None:
        record = build_recent_record(
            successful_state(download=8),
            THRESHOLDS,
        )
        self.assertEqual(record["minimum_download_mbps"], 10)
        self.assertEqual(record["maximum_ping_ms"], 200)
        self.assertTrue(record["low_download"])
        self.assertTrue(record["low_speed"])
        self.assertTrue(record["performance_problem"])

    def test_threshold_change_does_not_rewrite_old_record(self) -> None:
        record = build_recent_record(successful_state(download=15), THRESHOLDS)
        store = append_recent_result(default_recent_results(), record, 20)
        old_copy = json.loads(json.dumps(store["results"][0]))
        evaluate_performance(
            successful_state(download=15),
            {**THRESHOLDS, "minimum_download_mbps": 20},
            available=True,
        )
        self.assertEqual(store["results"][0], old_copy)
        self.assertEqual(store["results"][0]["minimum_download_mbps"], 10)

    def test_failed_status_does_not_add_recent_result(self) -> None:
        store = default_recent_results()
        state = update_runtime_status(
            successful_state(),
            "Error",
            attempted_at="2026-07-24T08:00:00Z",
            error="failed",
        )
        self.assertEqual(state["status"], "Error")
        self.assertEqual(recent_results_payload(store, 20)["count"], 0)

    def test_limit_trims_newest_first(self) -> None:
        store = default_recent_results()
        for index in range(8):
            state = successful_state(
                timestamp=f"2026-07-24T07:{index:02d}:00Z"
            )
            state["result_url"] = f"https://example/{index}"
            store = append_recent_result(
                store,
                build_recent_record(state, THRESHOLDS),
                5,
            )
        payload = recent_results_payload(store, 5)
        self.assertEqual(payload["count"], 5)
        self.assertEqual(payload["results"][0]["result_url"], "https://example/7")
        self.assertEqual(payload["results"][-1]["result_url"], "https://example/3")

    def test_duplicate_result_url_is_not_duplicated(self) -> None:
        record = build_recent_record(successful_state(), THRESHOLDS)
        store = append_recent_result(default_recent_results(), record, 20)
        store = append_recent_result(store, record, 20)
        self.assertEqual(len(store["results"]), 1)

    def test_no_1_0_backfill_when_file_is_missing(self) -> None:
        migrated = migrate_recent_results(None, 20)
        self.assertEqual(migrated, default_recent_results())


class FreshnessAndFailureTests(unittest.TestCase):
    def test_no_connectivity_preserves_last_measurement(self) -> None:
        state = successful_state(download=7)
        changed = update_runtime_status(
            state,
            "No connectivity",
            attempted_at="2026-07-24T08:00:00Z",
            error="offline",
        )
        self.assertEqual(changed["download_mbps"], 7)
        result = evaluate_performance(changed, THRESHOLDS, available=True)
        self.assertEqual(result["low_download"]["state"], "ON")

    def test_expired_result_is_unavailable(self) -> None:
        fresh = is_result_fresh(
            "2026-07-24T07:00:00Z",
            3600,
            now=datetime(2026, 7, 24, 8, 0, 1, tzinfo=timezone.utc),
        )
        self.assertFalse(fresh)
        evaluation = evaluate_performance(
            successful_state(download=7),
            THRESHOLDS,
            available=fresh,
        )
        self.assertFalse(evaluation["available"])

    def test_result_at_expiry_boundary_is_fresh(self) -> None:
        self.assertTrue(
            is_result_fresh(
                "2026-07-24T07:00:00Z",
                3600,
                now="2026-07-24T08:00:00Z",
            )
        )


class ParsingAndPersistenceTests(unittest.TestCase):
    def test_packet_loss_null_remains_null(self) -> None:
        raw = {
            "type": "result",
            "timestamp": "2026-07-24T07:00:00Z",
            "download": {"bandwidth": 1_000_000},
            "upload": {"bandwidth": 500_000},
            "ping": {"latency": 2.5, "jitter": 0.4},
            "packetLoss": None,
            "interface": {"externalIp": "203.0.113.10"},
            "server": {
                "id": 56519,
                "name": "OBIT",
                "location": "Almaty",
                "country": "Kazakhstan",
            },
            "result": {"url": "https://example/result"},
        }
        state = build_success_state(raw, "2026-07-24T07:00:01Z")
        self.assertIsNone(state["packet_loss"])

    def test_threshold_defaults_are_10_10_200(self) -> None:
        self.assertEqual(
            normalize_thresholds({}),
            {
                "minimum_download_mbps": 10,
                "minimum_upload_mbps": 10,
                "maximum_ping_ms": 200,
            },
        )

    def test_atomic_persistence_survives_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "thresholds.json"
            payload = normalize_thresholds({})
            atomic_write_json(path, payload)
            self.assertEqual(load_json(path, {}), payload)

    def test_server_list_parser(self) -> None:
        output = (
            "38516  Kazakhtelecom  Almaty  Kazakhstan\n"
            "70668  Hoster.KZ  Almaty  Kazakhstan\n"
        )
        servers = parse_server_list(output)
        self.assertEqual([item["id"] for item in servers], [38516, 70668])


if __name__ == "__main__":
    unittest.main()
