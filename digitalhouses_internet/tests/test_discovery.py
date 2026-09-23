from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from discovery import EVENT_SCHEMA_VERSION, build_discovery_payload


class DiscoveryTests(unittest.TestCase):
    def test_event_schema_version(self) -> None:
        self.assertEqual(EVENT_SCHEMA_VERSION, 2)

    def test_connectivity_entity_ids(self) -> None:
        components = build_discovery_payload("0.1.0")["components"]
        expected = {
            "google_connectivity": "binary_sensor.dh_internet_app_google_connectivity",
            "cloudflare_connectivity": "binary_sensor.dh_internet_app_cloudflare_connectivity",
            "internet_status": "binary_sensor.dh_internet_app_internet",
            "router_status": "binary_sensor.dh_internet_app_router_connectivity",
        }
        for key, entity_id in expected.items():
            with self.subTest(component=key):
                self.assertEqual(
                    components[key]["default_entity_id"],
                    entity_id,
                )

    def test_traffic_entities_are_conditional(self) -> None:
        without_traffic = build_discovery_payload("0.1.0")
        self.assertNotIn(
            "traffic_download_total", without_traffic["components"]
        )
        with_traffic = build_discovery_payload(
            "0.1.0", traffic_enabled=True
        )
        self.assertIn("traffic_download_total", with_traffic["components"])
        self.assertIn("traffic_history", with_traffic["components"])
        self.assertEqual(
            with_traffic["components"]["traffic_download_total"][
                "default_entity_id"
            ],
            "sensor.dh_internet_app_traffic_download_total",
        )

    def test_optional_router_entities_are_conditional(self) -> None:
        payload = build_discovery_payload(
            "0.1.0",
            wan_enabled=True,
            download_rate_enabled=True,
            upload_rate_enabled=True,
        )
        components = payload["components"]
        self.assertIn("router_wan_status", components)
        self.assertIn("router_download_rate", components)
        self.assertIn("router_upload_rate", components)

    def test_canonical_identity_and_runtime_diagnostics(self) -> None:
        payload = build_discovery_payload("0.1.0")
        self.assertEqual(
            payload["device"]["name"], "DigitalHouses Internet App"
        )
        components = payload["components"]
        for component in components.values():
            self.assertTrue(
                component["unique_id"].startswith("dh_internet_app_")
            )
        self.assertEqual(
            components["started_at"]["device_class"], "timestamp"
        )
        self.assertEqual(
            components["started_at"]["entity_category"], "diagnostic"
        )
        self.assertEqual(
            components["app_version"]["entity_category"], "diagnostic"
        )
        self.assertEqual(
            components["performance_problem"]["device_class"], "problem"
        )
        self.assertEqual(
            components["problems"]["entity_category"], "diagnostic"
        )


if __name__ == "__main__":
    unittest.main()
