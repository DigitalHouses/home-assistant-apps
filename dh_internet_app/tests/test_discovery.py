from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from discovery import (
    EVENT_SCHEMA_VERSION,
    OPTIONAL_COMPONENT_PLATFORMS,
    TOPICS,
    build_discovery_cleanup_payload,
    build_discovery_payload,
)


class DiscoveryTests(unittest.TestCase):
    def test_event_schema_version(self) -> None:
        self.assertEqual(EVENT_SCHEMA_VERSION, 2)

    def test_event_uses_raw_json_payload(self) -> None:
        event = build_discovery_payload("0.1.0")["components"]["event"]
        self.assertEqual(event["state_topic"], TOPICS["event"])
        self.assertNotIn("value_template", event)
        self.assertNotIn("json_attributes_topic", event)

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

    def test_optional_component_registry_matches_conditional_entities(self) -> None:
        payload = build_discovery_payload(
            "0.1.0",
            traffic_enabled=True,
            wan_enabled=True,
            download_rate_enabled=True,
            upload_rate_enabled=True,
        )
        self.assertEqual(
            set(OPTIONAL_COMPONENT_PLATFORMS),
            {
                "traffic_download_total",
                "traffic_upload_total",
                "traffic_download_month",
                "traffic_upload_month",
                "traffic_history",
                "router_wan_status",
                "router_download_rate",
                "router_upload_rate",
            },
        )
        self.assertTrue(
            set(OPTIONAL_COMPONENT_PLATFORMS)
            <= set(payload["components"])
        )

    def test_cleanup_payload_explicitly_removes_old_optional_component(self) -> None:
        payload = build_discovery_payload("0.1.0")
        cleanup = build_discovery_cleanup_payload(
            payload,
            {"router_wan_status", "traffic_history", "not_optional"},
        )
        self.assertEqual(
            cleanup["components"]["router_wan_status"],
            {"platform": "sensor"},
        )
        self.assertEqual(
            cleanup["components"]["traffic_history"],
            {"platform": "sensor"},
        )
        self.assertNotIn("not_optional", cleanup["components"])
        self.assertNotIn(
            "router_wan_status",
            payload["components"],
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
        for key, field in (
            ("router_wan_status", "wan_status"),
            ("router_download_rate", "download_rate_mbps"),
            ("router_upload_rate", "upload_rate_mbps"),
        ):
            with self.subTest(component=key):
                availability = components[key]["availability"]
                self.assertEqual(len(availability), 2)
                self.assertEqual(
                    availability[1]["topic"],
                    "DigitalHouses/Global/dh_internet_app/traffic",
                )
                self.assertIn(
                    f"value_json.router.{field}",
                    availability[1]["value_template"],
                )
                self.assertEqual(
                    components[key]["availability_mode"],
                    "all",
                )

    def test_speedtest_status_is_idle_or_running(self) -> None:
        component = build_discovery_payload("0.1.6")["components"][
            "speedtest_status"
        ]
        self.assertEqual(component["options"], ["idle", "running"])
        self.assertIn("last_result", component["json_attributes_template"])

    def test_router_rate_precision_is_one_decimal(self) -> None:
        components = build_discovery_payload(
            "0.1.6",
            download_rate_enabled=True,
            upload_rate_enabled=True,
        )["components"]
        for key, field in (
            ("router_download_rate", "download_rate_mbps"),
            ("router_upload_rate", "upload_rate_mbps"),
        ):
            template = components[key]["value_template"]
            self.assertIn("| round(1)", template)
            self.assertIn(
                f"value_json.router.{field} is not none",
                template,
            )

    def test_recorder_noise_is_suppressed(self) -> None:
        components = build_discovery_payload("0.1.9")["components"]

        availability = components["availability_month"]
        self.assertIn("| round(2)", availability["value_template"])
        self.assertIn("'month': value_json.month", availability["json_attributes_template"])
        self.assertNotIn("online_seconds", availability["json_attributes_template"])
        self.assertNotIn("offline_seconds", availability["json_attributes_template"])
        self.assertNotIn("elapsed_seconds", availability["json_attributes_template"])

        problems = components["problems"]
        self.assertIn("'problems': value_json.problems", problems["json_attributes_template"])
        self.assertNotIn("updated_at", problems["json_attributes_template"])

    def test_telemetry_delete_button_uses_fixed_command(self) -> None:
        component = build_discovery_payload("0.1.10")["components"][
            "delete_telemetry"
        ]
        self.assertEqual(
            component["default_entity_id"],
            "button.dh_internet_app_delete_telemetry",
        )
        self.assertEqual(component["command_topic"], TOPICS["command"])
        self.assertEqual(component["payload_press"], "DELETE_TELEMETRY")
        self.assertEqual(component["entity_category"], "config")

    def test_compact_server_discovery(self) -> None:
        components = build_discovery_payload("0.1.0")["components"]
        self.assertEqual(
            components["available_servers"]["default_entity_id"],
            "sensor.dh_internet_app_available_servers",
        )
        self.assertEqual(
            components["refresh_servers"]["default_entity_id"],
            "button.dh_internet_app_refresh_servers",
        )

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
