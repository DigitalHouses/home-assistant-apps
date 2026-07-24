from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from discovery import (  # noqa: E402
    DEVICE_ID,
    LEGACY_COMPONENT_IDENTITIES,
    build_discovery_payload,
)


TOPICS = {
    "state": "DigitalHouses/Global/speedtest/state",
    "command": "DigitalHouses/Global/speedtest/command",
    "app_availability": "DigitalHouses/Global/speedtest/availability",
    "result_availability": "DigitalHouses/Global/speedtest/result_availability",
    "connectivity": "DigitalHouses/Global/speedtest/connectivity",
    "servers": "DigitalHouses/Global/speedtest/servers",
    "thresholds": "DigitalHouses/Global/speedtest/thresholds",
    "problems": "DigitalHouses/Global/speedtest/problems",
    "recent_results": "DigitalHouses/Global/speedtest/recent_results",
    "minimum_download_command": (
        "DigitalHouses/Global/speedtest/thresholds/minimum_download/set"
    ),
    "minimum_upload_command": (
        "DigitalHouses/Global/speedtest/thresholds/minimum_upload/set"
    ),
    "maximum_ping_command": (
        "DigitalHouses/Global/speedtest/thresholds/maximum_ping/set"
    ),
}


class DiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = build_discovery_payload(
            app_version="1.1.0",
            expire_after_seconds=14400,
            topics=TOPICS,
        )
        self.components = self.payload["components"]

    def test_device_identifier_is_unchanged(self) -> None:
        self.assertEqual(
            self.payload["device"]["identifiers"],
            [DEVICE_ID],
        )

    def test_all_legacy_unique_ids_and_entity_ids_are_unchanged(self) -> None:
        for key, (unique_id, entity_id) in LEGACY_COMPONENT_IDENTITIES.items():
            with self.subTest(component=key):
                self.assertEqual(self.components[key]["unique_id"], unique_id)
                self.assertEqual(
                    self.components[key]["default_entity_id"],
                    entity_id,
                )

    def test_new_threshold_numbers_have_expected_ranges(self) -> None:
        self.assertEqual(self.components["minimum_download"]["min"], 1)
        self.assertEqual(self.components["minimum_download"]["max"], 10000)
        self.assertEqual(self.components["minimum_upload"]["step"], 1)
        self.assertEqual(self.components["maximum_ping"]["max"], 1000)
        self.assertEqual(self.components["maximum_ping"]["mode"], "box")

    def test_problem_sensors_use_problem_device_class(self) -> None:
        for key in (
            "low_download",
            "low_upload",
            "high_ping",
            "performance_problem",
        ):
            with self.subTest(component=key):
                self.assertEqual(
                    self.components[key]["device_class"],
                    "problem",
                )
                self.assertEqual(
                    self.components[key]["platform"],
                    "binary_sensor",
                )

    def test_problem_sensors_require_fresh_result_availability(self) -> None:
        availability = self.components["low_download"]["availability"]
        topics = [item["topic"] for item in availability]
        self.assertIn(TOPICS["app_availability"], topics)
        self.assertIn(TOPICS["result_availability"], topics)
        self.assertEqual(
            self.components["low_download"]["availability_mode"],
            "all",
        )

    def test_recent_results_is_diagnostic_sensor(self) -> None:
        component = self.components["recent_results"]
        self.assertEqual(component["platform"], "sensor")
        self.assertEqual(component["entity_category"], "diagnostic")
        self.assertEqual(
            component["default_entity_id"],
            "sensor.internet_speed_recent_results",
        )


if __name__ == "__main__":
    unittest.main()
