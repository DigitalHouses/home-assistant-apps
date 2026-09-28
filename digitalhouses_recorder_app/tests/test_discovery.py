import sys
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parents[1]
        / "rootfs"
        / "app"
    ),
)

from discovery import (
    APP_AVAILABILITY_TOPIC,
    BASE_TOPIC,
    DEVICE_ID,
    DISK_USAGE_THRESHOLD_COMMAND_TOPIC,
    DISK_USAGE_THRESHOLD_STATE_TOPIC,
    EVENT_TOPIC,
    LEGACY_BASE_TOPIC,
    LEGACY_DEVICE_ID,
    LEGACY_DISK_USAGE_THRESHOLD_COMMAND_TOPIC,
    LEGACY_EVENT_TOPIC,
    LEGACY_REFRESH_COMMAND_TOPIC,
    REFRESH_COMMAND_TOPIC,
    STATE_RETAIN,
    TELEMETRY_DELETE_COMMAND_TOPIC,
    build_discovery_payload,
    build_legacy_discovery_payload,
)


class CanonicalDiscoveryTests(unittest.TestCase):
    def test_canonical_identity_and_common_diagnostics(self):
        payload = build_discovery_payload("0.1.15")
        components = payload["components"]

        self.assertEqual(
            BASE_TOPIC,
            "DigitalHouses/Global/digitalhouses_recorder_app",
        )
        self.assertEqual(
            DEVICE_ID,
            "digitalhouses_recorder_app",
        )
        self.assertEqual(
            payload["device"]["identifiers"],
            ["digitalhouses_recorder_app"],
        )
        self.assertEqual(
            payload["device"]["sw_version"],
            "0.1.15",
        )
        self.assertEqual(
            payload["origin"]["sw_version"],
            "0.1.15",
        )

        self.assertEqual(
            components["db_start"]["default_entity_id"],
            "sensor.dh_recorder_app_db_start",
        )
        self.assertEqual(
            components["db_version"]["default_entity_id"],
            "sensor.dh_recorder_app_db_version",
        )
        self.assertEqual(
            components["db_connected"]["default_entity_id"],
            "binary_sensor.dh_recorder_app_db_connected",
        )
        self.assertEqual(
            components["recorder_writing"][
                "default_entity_id"
            ],
            "binary_sensor.dh_recorder_app_recorder_writing",
        )
        self.assertEqual(
            components["app_version"]["default_entity_id"],
            "sensor.dh_recorder_app_version",
        )
        self.assertEqual(
            components["app_started_at"][
                "default_entity_id"
            ],
            "sensor.dh_recorder_app_started_at",
        )
        self.assertEqual(
            components["app_started_at"]["device_class"],
            "timestamp",
        )
        self.assertEqual(
            components["app_version"]["entity_category"],
            "diagnostic",
        )
        self.assertEqual(
            components["database_type"]["default_entity_id"],
            "sensor.dh_recorder_app_database_type",
        )
        self.assertEqual(len(components), 25)
        self.assertTrue(STATE_RETAIN)

    def test_canonical_unique_ids_do_not_collide(self):
        components = build_discovery_payload(
            "0.1.15",
            include_storage=True,
        )["components"]
        unique_ids = [
            component["unique_id"]
            for component in components.values()
        ]
        self.assertEqual(
            len(unique_ids),
            len(set(unique_ids)),
        )
        self.assertNotEqual(
            components["db_version"]["unique_id"],
            components["app_version"]["unique_id"],
        )

    def test_event_and_control_topics_are_canonical(self):
        components = build_discovery_payload(
            "0.1.15"
        )["components"]

        event_component = components["diagnostic_event"]
        self.assertEqual(
            event_component["default_entity_id"],
            "event.dh_recorder_app_diagnostic",
        )
        self.assertEqual(
            event_component["state_topic"],
            EVENT_TOPIC,
        )
        self.assertEqual(
            EVENT_TOPIC,
            (
                "DigitalHouses/Global/"
                "digitalhouses_recorder_app/event/diagnostic"
            ),
        )

        refresh = components["db_refresh"]
        self.assertEqual(
            refresh["default_entity_id"],
            "button.dh_recorder_app_db_refresh",
        )
        self.assertEqual(
            refresh["command_topic"],
            REFRESH_COMMAND_TOPIC,
        )

        threshold = components[
            "db_disk_usage_threshold"
        ]
        self.assertEqual(
            threshold["default_entity_id"],
            (
                "number.dh_recorder_app_"
                "db_disk_usage_threshold"
            ),
        )
        self.assertEqual(
            threshold["state_topic"],
            DISK_USAGE_THRESHOLD_STATE_TOPIC,
        )
        self.assertEqual(
            threshold["command_topic"],
            DISK_USAGE_THRESHOLD_COMMAND_TOPIC,
        )

        delete = components["delete_telemetry"]
        self.assertEqual(
            delete["default_entity_id"],
            "button.dh_recorder_app_delete_telemetry",
        )
        self.assertEqual(
            delete["command_topic"],
            TELEMETRY_DELETE_COMMAND_TOPIC,
        )

    def test_db_connected_waits_for_observation(self):
        component = build_discovery_payload(
            "0.1.15"
        )["components"]["db_connected"]
        topics = {
            item["topic"]
            for item in component["availability"]
        }
        self.assertIn(APP_AVAILABILITY_TOPIC, topics)
        self.assertIn(
            (
                "DigitalHouses/Global/"
                "digitalhouses_recorder_app/"
                "database_status_availability"
            ),
            topics,
        )


class LegacyBridgeDiscoveryTests(unittest.TestCase):
    def test_legacy_device_topics_entities_and_unique_ids_are_stable(self):
        payload = build_legacy_discovery_payload(
            "0.1.15"
        )
        components = payload["components"]

        self.assertEqual(
            LEGACY_BASE_TOPIC,
            "DigitalHouses/Global/db_monitoring",
        )
        self.assertEqual(
            LEGACY_DEVICE_ID,
            "digitalhouses_db_monitoring",
        )
        self.assertEqual(
            payload["device"]["identifiers"],
            ["digitalhouses_db_monitoring"],
        )
        self.assertEqual(
            components["db_start"]["unique_id"],
            "digitalhouses_db_monitoring_db_start",
        )
        self.assertEqual(
            components["db_start"]["default_entity_id"],
            "sensor.dh_db_start",
        )
        self.assertEqual(
            components["db_version"]["unique_id"],
            "digitalhouses_db_monitoring_db_version",
        )
        self.assertEqual(
            components["db_version"]["default_entity_id"],
            "sensor.dh_db_version",
        )
        self.assertEqual(
            components["recorder_writing"]["unique_id"],
            (
                "digitalhouses_db_monitoring_"
                "recorder_writing"
            ),
        )
        self.assertEqual(
            components["recorder_writing"][
                "default_entity_id"
            ],
            "binary_sensor.dh_db_recorder_writing",
        )
        self.assertEqual(
            components["db_refresh"]["unique_id"],
            "digitalhouses_db_monitoring_db_refresh",
        )
        self.assertEqual(
            components["db_refresh"]["default_entity_id"],
            "button.dh_db_refresh",
        )
        self.assertEqual(
            components["diagnostic_event"]["unique_id"],
            (
                "digitalhouses_db_monitoring_"
                "diagnostic_event"
            ),
        )
        self.assertEqual(
            components["diagnostic_event"][
                "default_entity_id"
            ],
            "event.dh_db_diagnostic",
        )
        self.assertEqual(
            components["diagnostic_event"]["state_topic"],
            LEGACY_EVENT_TOPIC,
        )
        self.assertEqual(
            components["db_refresh"]["command_topic"],
            LEGACY_REFRESH_COMMAND_TOPIC,
        )
        self.assertEqual(
            components["db_disk_usage_threshold"][
                "command_topic"
            ],
            LEGACY_DISK_USAGE_THRESHOLD_COMMAND_TOPIC,
        )
        self.assertEqual(len(components), 19)

    def test_legacy_bridge_does_not_create_canonical_only_controls(self):
        components = build_legacy_discovery_payload(
            "0.1.15"
        )["components"]
        self.assertNotIn("app_version", components)
        self.assertNotIn("app_started_at", components)
        self.assertNotIn("database_type", components)
        self.assertNotIn("delete_telemetry", components)

    def test_legacy_bridge_uses_canonical_lwt_guard(self):
        component = build_legacy_discovery_payload(
            "0.1.15"
        )["components"]["db_start"]
        self.assertEqual(
            component["availability"][0]["topic"],
            APP_AVAILABILITY_TOPIC,
        )


class StorageAndRankingTests(unittest.TestCase):
    def test_storage_entities_follow_identity_namespace(self):
        canonical = build_discovery_payload(
            "0.1.15",
            include_storage=True,
        )["components"]
        legacy = build_legacy_discovery_payload(
            "0.1.15",
            include_storage=True,
        )["components"]

        self.assertEqual(
            canonical["db_disk_free"][
                "default_entity_id"
            ],
            "sensor.dh_recorder_app_db_disk_free",
        )
        self.assertEqual(
            legacy["db_disk_free"][
                "default_entity_id"
            ],
            "sensor.dh_db_disk_free",
        )

    def test_record_ui_sensors_are_scalar_k_values(self):
        components = build_discovery_payload(
            "0.1.18",
            include_storage=True,
        )["components"]
        expected = {
            "db_records_per_hour": "K rec/h",
            "db_records": "K records",
            "db_yesterday_records": "K records",
            "db_current_hour_records": "K records",
            "db_today_records": "K records",
        }
        for key, unit in expected.items():
            component = components[key]
            self.assertEqual(
                component["unit_of_measurement"],
                unit,
            )
            self.assertNotIn(
                "json_attributes_topic",
                component,
            )
            self.assertNotIn(
                "json_attributes_template",
                component,
            )

        self.assertEqual(
            components["db_current_hour_records"][
                "default_entity_id"
            ],
            (
                "sensor.dh_recorder_app_"
                "db_current_hour_records"
            ),
        )
        self.assertEqual(
            components["db_today_records"][
                "default_entity_id"
            ],
            "sensor.dh_recorder_app_db_today_records",
        )

    def test_ranking_topics_are_not_main_state_topic(self):
        components = build_discovery_payload(
            "0.1.15"
        )["components"]
        for key in (
            "db_top_entities_24h",
            "db_top_entities_all_time",
        ):
            component = components[key]
            self.assertEqual(
                component["state_topic"],
                component["json_attributes_topic"],
            )
            self.assertNotEqual(
                component["state_topic"],
                (
                    "DigitalHouses/Global/"
                    "digitalhouses_recorder_app/state"
                ),
            )
            self.assertEqual(
                component["value_template"],
                "{{ value_json.top_records }}",
            )
            self.assertEqual(
                component["unit_of_measurement"],
                "records",
            )
            self.assertEqual(
                component["suggested_display_precision"],
                0,
            )


if __name__ == "__main__":
    unittest.main()
