import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rootfs" / "app"))

from discovery import BASE_TOPIC, build_discovery_payload


class DiscoveryTests(unittest.TestCase):
    def test_common_entities_and_runtime_diagnostics(self):
        payload = build_discovery_payload("0.1.0")
        components = payload["components"]

        self.assertEqual(BASE_TOPIC, "DigitalHouses/Global/backblaze")
        self.assertEqual(payload["device"]["identifiers"], ["digitalhouses_backblaze"])
        self.assertEqual(payload["device"]["sw_version"], "0.1.0")
        self.assertEqual(
            components["total_used"]["default_entity_id"],
            "sensor.dh_backblaze_storage_used",
        )
        self.assertEqual(
            components["app_version"]["default_entity_id"],
            "sensor.dh_backblaze_app_version",
        )
        self.assertEqual(components["app_version"]["entity_category"], "diagnostic")
        self.assertEqual(
            components["app_started_at"]["device_class"],
            "timestamp",
        )
        self.assertEqual(
            components["app_started_at"]["entity_category"],
            "diagnostic",
        )
        self.assertEqual(
            components["refresh"]["default_entity_id"],
            "button.dh_backblaze_refresh",
        )
        self.assertEqual(
            components["telemetry_delete"]["default_entity_id"],
            "button.dh_backblaze_delete_telemetry",
        )

    def test_bucket_entities_are_dynamic_and_named(self):
        payload = build_discovery_payload(
            "0.1.0",
            [{"bucket_id": "bucket-id", "bucket_name": "HA-Backups"}],
        )
        components = payload["components"]
        used = components["bucket_bucket-id_used"]
        self.assertEqual(
            used["default_entity_id"],
            "sensor.dh_backblaze_ha_backups_used",
        )
        self.assertEqual(used["unit_of_measurement"], "B")
        self.assertEqual(
            components["bucket_bucket-id_files"]["default_entity_id"],
            "sensor.dh_backblaze_ha_backups_files",
        )


if __name__ == "__main__":
    unittest.main()
