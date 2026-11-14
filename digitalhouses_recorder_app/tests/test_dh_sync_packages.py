"""Regression coverage for existing Recorder HA packages published to DH Sync.

Only stdlib is used so the Recorder App CI job needs no new dependencies.
Actual YAML structure is independently checked by DH Sync's package parser.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "rootfs" / "app"))
from contracts import EVENT_REQUIRED_FIELDS  # noqa: E402

COMMON = APP / "packages" / "common" / "dh_recorder_app.yaml"
NOTIFICATIONS = (
    APP / "packages" / "locales" / "ru"
    / "dh_recorder_app_notification_package.yaml"
)
TOPIC = "DigitalHouses/Global/digitalhouses_recorder_app/event/diagnostic"

RECORDER_ENTITIES = (
    "binary_sensor.dh_recorder_app_db_connected",
    "binary_sensor.dh_recorder_app_recorder_writing",
    "sensor.dh_recorder_app_db_last_age",
    "sensor.dh_recorder_app_db_depth",
    "sensor.dh_recorder_app_db_records",
    "sensor.dh_recorder_app_db_size",
    "sensor.dh_recorder_app_db_today_records",
    "sensor.dh_recorder_app_db_current_hour_records",
    "sensor.dh_recorder_app_db_disk_free",
    "sensor.dh_recorder_app_db_disk_used",
    "sensor.dh_recorder_app_db_disk_total",
    "sensor.dh_recorder_app_db_disk_used_percentage",
)


class RecorderDHSynchronizationPackageTests(unittest.TestCase):
    def test_common_package_path_and_single_stable_key(self):
        self.assertEqual(
            COMMON.relative_to(APP).as_posix(),
            "packages/common/dh_recorder_app.yaml",
        )
        source = COMMON.read_text(encoding="utf-8")
        keys = re.findall(r"(?m)^([a-z][a-z_0-9]*):\s*$", source)
        self.assertEqual(keys, ["dh_recorder_app_package"])
        self.assertIn("\n  recorder:\n    include:\n      entities:\n", source)

    def test_original_recorder_entities_preserved_exactly(self):
        source = COMMON.read_text(encoding="utf-8")
        entities = re.findall(
            r"(?m)^        - ((?:binary_sensor|sensor)\.[a-z0-9_]+)$",
            source,
        )
        self.assertEqual(entities, list(RECORDER_ENTITIES))
        self.assertEqual(len(entities), len(set(entities)))
        self.assertNotIn("sensor.dh_recorder_app_version", source)
        self.assertNotIn("sensor.dh_recorder_app_db_records_per_hour", source)

    def test_notification_package_has_existing_key_and_automation_id(self):
        self.assertEqual(
            NOTIFICATIONS.relative_to(APP).as_posix(),
            "packages/locales/ru/dh_recorder_app_notification_package.yaml",
        )
        source = NOTIFICATIONS.read_text(encoding="utf-8")
        keys = re.findall(r"(?m)^([a-z][a-z_0-9]*):\s*$", source)
        self.assertEqual(keys, ["dh_recorder_app_notification_package"])
        self.assertEqual(source.count("id: dh_recorder_notifications"), 1)
        self.assertIn("alias: DH Recorder · Storage Notifications", source)
        self.assertIn("mode: single", source)

    def test_notifications_consume_real_machine_events_directly(self):
        source = NOTIFICATIONS.read_text(encoding="utf-8")
        self.assertEqual(source.count("trigger: mqtt"), 2)
        self.assertEqual(source.count("topic: " + TOPIC), 2)
        self.assertEqual(source.count('value_template: "{{ value_json.event_type }}"'), 2)
        for event in ("storage_usage_high", "storage_usage_normal"):
            with self.subTest(event=event):
                self.assertIn(event, EVENT_REQUIRED_FIELDS)
                self.assertEqual(source.count("payload: " + event), 1)
                self.assertEqual(source.count("id: " + event), 2)
        self.assertEqual(source.count("condition: trigger"), 2)
        self.assertNotIn("notification_envelope", source.lower())

    def test_global_write2log_and_original_russian_messages(self):
        source = NOTIFICATIONS.read_text(encoding="utf-8")
        self.assertIn("shared global script.write2log", source)
        self.assertEqual(source.count("- action: script.write2log"), 2)
        self.assertEqual(source.count("title: "), 2)
        self.assertEqual(source.count("message: >-"), 2)
        self.assertIn("💾⚠️ Recorder: заполнение диска", source)
        self.assertIn("💾✅ Recorder: заполнение диска в норме", source)
        for field in (
            "used_percent",
            "used_gb",
            "total_gb",
            "free_gb",
            "threshold_percent",
        ):
            with self.subTest(field=field):
                self.assertEqual(
                    source.count("trigger.payload_json." + field), 2,
                )
                self.assertIn(field, EVENT_REQUIRED_FIELDS["storage_usage_high"])
                self.assertIn(field, EVENT_REQUIRED_FIELDS["storage_usage_normal"])
        self.assertNotIn("| tojson", source)
        self.assertNotIn("192.168.", source)
        self.assertNotIn("notify.mobile_app_", source)


if __name__ == "__main__":
    unittest.main()
