import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP))

from discovery import build_discovery_payload


class DiscoveryTests(unittest.TestCase):
    def test_common_diagnostics_and_bucket_entities(self):
        payload = build_discovery_payload(
            app_version="0.1.0",
            topics={
                "state": "DigitalHouses/Global/backblaze/state",
                "command": "DigitalHouses/Global/backblaze/command",
                "availability": "DigitalHouses/Global/backblaze/availability",
            },
            buckets=[
                {
                    "bucket_id": "bucket123",
                    "bucket_name": "ha-backups",
                    "bucket_type": "allPrivate",
                }
            ],
        )
        components = payload["components"]
        self.assertEqual(
            components["app_version"]["default_entity_id"],
            "sensor.dh_backblaze_app_version",
        )
        self.assertEqual(
            components["app_started_at"]["device_class"],
            "timestamp",
        )
        self.assertEqual(
            components["bucket_ha_backups_storage"]["default_entity_id"],
            "sensor.dh_backblaze_ha_backups_storage_used",
        )
        self.assertEqual(payload["device"]["sw_version"], "0.1.0")
        self.assertEqual(payload["origin"]["sw_version"], "0.1.0")


if __name__ == "__main__":
    unittest.main()
