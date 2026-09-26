from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = (
    Path(__file__).resolve().parents[1]
    / "rootfs"
    / "app"
)
sys.path.insert(0, str(APP_DIR))

from contracts import (
    EVENT_REQUIRED_FIELDS,
    validate_machine_event,
    validate_release_version,
    validate_runtime_state,
    validate_static_db_metrics,
)


class RuntimeContractTests(unittest.TestCase):
    def test_release_version_is_required_and_semver(self):
        self.assertEqual(
            validate_release_version("0.1.15"),
            "0.1.15",
        )
        for invalid in (
            None,
            "",
            "unknown",
            "0.1.15-local",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_release_version(invalid)

    def test_runtime_diagnostics_are_required(self):
        valid = {
            "version": "0.1.15",
            "started_at": "2026-09-27T03:00:00+05:00",
            "db_type": "postgresql",
        }
        validate_runtime_state(valid)

        for field in ("version", "started_at", "db_type"):
            broken = dict(valid)
            broken.pop(field)
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    validate_runtime_state(broken)

    def test_started_at_must_be_timezone_aware(self):
        with self.assertRaises(ValueError):
            validate_runtime_state(
                {
                    "version": "0.1.15",
                    "started_at": "2026-09-27T03:00:00",
                    "db_type": "postgresql",
                }
            )

    def test_static_database_identity_is_required(self):
        valid = {
            "db_name": "homeassistant",
            "db_user": "recorder_monitor",
            "db_version": "PostgreSQL 17.5",
        }
        self.assertEqual(
            validate_static_db_metrics(valid),
            valid,
        )
        for field in valid:
            broken = dict(valid)
            broken[field] = ""
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    validate_static_db_metrics(broken)


class MachineEventContractTests(unittest.TestCase):
    def _payload(
        self,
        event_type: str,
    ) -> dict[str, object]:
        common: dict[str, object] = {
            "schema_version": 2,
            "event_type": event_type,
            "observed_at": (
                "2026-09-27T03:00:00+05:00"
            ),
        }
        if event_type == "db_connection_lost":
            common.update(
                {
                    "database_engine": "postgresql",
                    "database_name": "homeassistant",
                }
            )
        elif event_type == "db_connection_restored":
            common.update(
                {
                    "database_engine": "postgresql",
                    "database_name": "homeassistant",
                    "outage_seconds": 12,
                }
            )
        elif event_type.startswith("recorder_writing_"):
            common.update(
                {
                    "last_record_at": (
                        "2026-09-27T02:59:58+05:00"
                    ),
                    "last_age_seconds": 2,
                    "stale_threshold_seconds": 300,
                }
            )
        elif event_type.startswith("storage_usage_"):
            common.update(
                {
                    "used_percent": 81.0,
                    "used_gb": 81.0,
                    "free_gb": 19.0,
                    "total_gb": 100.0,
                    "threshold_percent": 80.0,
                    "cause": "measurement",
                }
            )
        return common

    def test_every_event_type_accepts_valid_payload(self):
        for event_type in EVENT_REQUIRED_FIELDS:
            with self.subTest(event_type=event_type):
                validate_machine_event(
                    self._payload(event_type)
                )

    def test_each_required_event_field_fails_when_missing(self):
        for event_type, fields in EVENT_REQUIRED_FIELDS.items():
            for field in fields:
                broken = self._payload(event_type)
                broken.pop(field)
                with self.subTest(
                    event_type=event_type,
                    field=field,
                ):
                    with self.assertRaises(ValueError):
                        validate_machine_event(broken)

    def test_invalid_required_types_fail(self):
        broken = self._payload(
            "db_connection_restored"
        )
        broken["outage_seconds"] = "12"
        with self.assertRaises(ValueError):
            validate_machine_event(broken)

        broken = self._payload("storage_usage_high")
        broken["used_percent"] = False
        with self.assertRaises(ValueError):
            validate_machine_event(broken)

    def test_nullable_recorder_observation_fields_are_optional(self):
        payload = self._payload(
            "recorder_writing_stopped"
        )
        payload["last_record_at"] = None
        payload["last_age_seconds"] = None
        validate_machine_event(payload)

    def test_presentation_fields_are_rejected(self):
        payload = self._payload(
            "db_connection_lost"
        )
        payload["message"] = "Database is down"
        with self.assertRaises(ValueError):
            validate_machine_event(payload)


if __name__ == "__main__":
    unittest.main()
