from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from contracts import EVENT_SCHEMA_VERSION, validate_machine_event


def payload(event_type: str, **fields):
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_type": event_type,
        "timestamp": "2026-09-27T16:00:00+05:00",
        **fields,
    }


VALID_EVENTS = {
    "connection_lost": payload(
        "connection_lost",
        router_up=True,
        attempts=3,
    ),
    "connection_restored": payload(
        "connection_restored",
        duration_seconds=65,
    ),
    "recovery_started": payload(
        "recovery_started",
        cycle=1,
        mode="smart",
        targets=["ont"],
        reason="internet_down_router_up",
    ),
    "recovery_action": payload(
        "recovery_action",
        cycle=1,
        target="ont",
        action="switch",
        entity_id="switch.ont",
    ),
    "recovery_stopped": payload(
        "recovery_stopped",
        reason="user",
    ),
    "recovery_exhausted": payload(
        "recovery_exhausted",
        cycles=3,
        cooldown_seconds=900,
    ),
    "recovery_error": payload(
        "recovery_error",
        error="Home Assistant API unavailable",
    ),
    "speedtest_completed": payload(
        "speedtest_completed",
        download_mbps=100.0,
        upload_mbps=50.0,
        ping_ms=10.0,
        jitter_ms=None,
        packet_loss_pct=0.0,
    ),
    "speedtest_failed": payload(
        "speedtest_failed",
        reason="Ookla exited with code 1",
    ),
    "performance_problem_started": payload(
        "performance_problem_started",
        reasons=["low_download"],
        download_mbps=5.0,
        upload_mbps=20.0,
        ping_ms=10.0,
        minimum_download_mbps=10,
        minimum_upload_mbps=10,
        maximum_ping_ms=200,
    ),
    "performance_problem_recovered": payload(
        "performance_problem_recovered",
        previous_reasons=["low_download"],
        download_mbps=20.0,
        upload_mbps=20.0,
        ping_ms=10.0,
    ),
    "performance_problem_updated": payload(
        "performance_problem_updated",
        previous_reasons=["low_download"],
        reasons=["low_download", "high_ping"],
        download_mbps=5.0,
        upload_mbps=20.0,
        ping_ms=300.0,
    ),
}


class MachineEventContractTests(unittest.TestCase):
    def test_all_supported_event_shapes_are_valid(self) -> None:
        for event_type, event in VALID_EVENTS.items():
            with self.subTest(event_type=event_type):
                validate_machine_event(event)

    def test_unknown_event_type_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_machine_event(payload("mystery_event"))

    def test_missing_required_field_is_rejected(self) -> None:
        broken = dict(VALID_EVENTS["connection_lost"])
        broken.pop("attempts")
        with self.assertRaises(ValueError):
            validate_machine_event(broken)

    def test_extra_field_is_rejected(self) -> None:
        broken = dict(VALID_EVENTS["connection_restored"])
        broken["message"] = "presentation must not be in machine payload"
        with self.assertRaises(ValueError):
            validate_machine_event(broken)

    def test_wrong_field_type_is_rejected(self) -> None:
        broken = dict(VALID_EVENTS["connection_lost"])
        broken["router_up"] = "yes"
        with self.assertRaises(ValueError):
            validate_machine_event(broken)

    def test_timestamp_requires_timezone(self) -> None:
        broken = dict(VALID_EVENTS["connection_restored"])
        broken["timestamp"] = "2026-09-27T16:00:00"
        with self.assertRaises(ValueError):
            validate_machine_event(broken)


if __name__ == "__main__":
    unittest.main()
