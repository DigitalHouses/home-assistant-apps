import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rootfs" / "app"))

from discovery import (
    API_OBSERVED_TOPIC,
    APP_AVAILABILITY_TOPIC,
    BASE_TOPIC,
    DATA_AVAILABILITY_TOPIC,
    DISCOVERY_SCHEMA_VERSION,
    REFRESH_OPERATION_TOPIC,
    STORAGE_TREE_TOPIC,
    bucket_state_topic,
    build_discovery_payload,
    discovery_cleanup_payload,
    dynamic_discovery_manifest,
    load_discovery_manifest,
    mark_discovery_schema,
    needs_discovery_reset,
    removed_discovery_components,
    save_discovery_manifest,
)


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
            components["total_used"]["name"],
            "Total used",
        )
        self.assertEqual(
            components["total_used"]["value_template"],
            "{{ (value_json.stored_bytes / 1073741824) | round(1) }}",
        )
        self.assertNotIn("entity_category", components["total_used"])
        self.assertNotIn("entity_category", components["bucket_count"])
        self.assertNotIn("entity_category", components["total_files"])
        self.assertEqual(components["total_files"]["name"], "Total files")
        self.assertEqual(
            components["total_files"]["value_template"],
            "{{ value_json.current_files }}",
        )
        self.assertNotIn("entity_category", components["total_versions"])
        self.assertEqual(
            components["total_used"]["unit_of_measurement"],
            "GiB",
        )
        self.assertEqual(
            components["total_used"]["suggested_display_precision"],
            1,
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
            components["refresh"]["entity_category"],
            "config",
        )
        self.assertEqual(
            components["telemetry_delete"]["default_entity_id"],
            "button.dh_backblaze_delete_telemetry",
        )

        self.assertEqual(
            components["storage_tree"]["default_entity_id"],
            "sensor.dh_backblaze_storage_tree",
        )
        self.assertEqual(
            components["storage_tree"]["state_topic"],
            STORAGE_TREE_TOPIC,
        )
        self.assertEqual(
            components["storage_tree"]["json_attributes_topic"],
            STORAGE_TREE_TOPIC,
        )
        self.assertNotIn("entity_category", components["storage_tree"])
        self.assertEqual(
            components["last_refresh"]["default_entity_id"],
            "sensor.dh_backblaze_last_refresh",
        )
        self.assertEqual(
            components["last_refresh"]["device_class"],
            "timestamp",
        )
        self.assertEqual(
            components["refresh_state"]["default_entity_id"],
            "sensor.dh_backblaze_refresh_state",
        )
        self.assertEqual(
            components["refresh_state"]["state_topic"],
            REFRESH_OPERATION_TOPIC,
        )
        self.assertEqual(
            components["refresh_state"]["json_attributes_topic"],
            REFRESH_OPERATION_TOPIC,
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
        self.assertEqual(used["unit_of_measurement"], "GiB")
        self.assertEqual(used["suggested_display_precision"], 1)
        self.assertNotIn("json_attributes_topic", used)
        self.assertNotIn("entity_category", used)
        self.assertEqual(
            components["bucket_bucket-id_files"]["default_entity_id"],
            "sensor.dh_backblaze_ha_backups_files",
        )

    def test_removed_bucket_components_are_explicit_removal_stubs(self):
        payload = build_discovery_payload(
            "0.1.0",
            [{"bucket_id": "active-id", "bucket_name": "Active"}],
            removed_buckets=[
                {"bucket_id": "removed-id", "bucket_name": "Removed"},
                {"bucket_id": "active-id", "bucket_name": "Active"},
            ],
        )
        components = payload["components"]

        self.assertEqual(
            components["bucket_removed-id_used"],
            {"platform": "sensor"},
        )
        self.assertEqual(
            components["bucket_removed-id_files"],
            {"platform": "sensor"},
        )
        self.assertEqual(
            components["bucket_removed-id_versions"],
            {"platform": "sensor"},
        )
        self.assertIn("value_template", components["bucket_active-id_used"])

    def test_data_entities_use_source_availability_gates(self):
        payload = build_discovery_payload(
            "0.1.11",
            [{"bucket_id": "bucket-id", "bucket_name": "HA-Backups"}],
        )
        components = payload["components"]

        total_topics = {
            item["topic"] for item in components["total_used"]["availability"]
        }
        self.assertEqual(
            total_topics,
            {APP_AVAILABILITY_TOPIC, DATA_AVAILABILITY_TOPIC},
        )

        api_topics = {
            item["topic"] for item in components["api_connected"]["availability"]
        }
        self.assertEqual(
            api_topics,
            {APP_AVAILABILITY_TOPIC, API_OBSERVED_TOPIC},
        )

        version_topics = {
            item["topic"] for item in components["app_version"]["availability"]
        }
        self.assertEqual(version_topics, {APP_AVAILABILITY_TOPIC})

        bucket_topics = {
            item["topic"]
            for item in components["bucket_bucket-id_used"]["availability"]
        }
        self.assertEqual(
            bucket_topics,
            {APP_AVAILABILITY_TOPIC, DATA_AVAILABILITY_TOPIC},
        )

        tree_topics = {
            item["topic"] for item in components["storage_tree"]["availability"]
        }
        self.assertEqual(
            tree_topics,
            {APP_AVAILABILITY_TOPIC, DATA_AVAILABILITY_TOPIC},
        )

        refresh_state_topics = {
            item["topic"] for item in components["refresh_state"]["availability"]
        }
        self.assertEqual(refresh_state_topics, {APP_AVAILABILITY_TOPIC})

    def test_dynamic_manifest_survives_restart_and_removes_missing_bucket(self):
        old_payload = build_discovery_payload(
            "0.1.11",
            [{"bucket_id": "removed-id", "bucket_name": "Removed"}],
        )
        new_payload = build_discovery_payload("0.1.11")
        old_manifest = dynamic_discovery_manifest(old_payload)
        new_manifest = dynamic_discovery_manifest(new_payload)

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            save_discovery_manifest(old_manifest, path)
            restored = load_discovery_manifest(path)

        self.assertEqual(restored, old_manifest)

        removals, topics = removed_discovery_components(
            restored or {},
            new_manifest,
        )
        self.assertEqual(
            set(removals),
            {
                "bucket_removed-id_used",
                "bucket_removed-id_files",
                "bucket_removed-id_versions",
            },
        )
        self.assertEqual(topics, (bucket_state_topic("removed-id"),))

        cleanup = discovery_cleanup_payload(new_payload, removals)
        for key in removals:
            self.assertEqual(cleanup["components"][key], {"platform": "sensor"})

    def test_invalid_manifest_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            path.write_text(
                '{"schema_version":1,"components":{"bucket_x_used":{"platform":"sensor"}}}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid topics"):
                load_discovery_manifest(path)

    def test_support_url_uses_canonical_repository_directory(self):
        payload = build_discovery_payload("0.1.11")
        self.assertTrue(
            payload["origin"]["support_url"].endswith(
                "/digitalhouses_backblaze_app"
            )
        )

    def test_discovery_schema_reset_is_one_time(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "discovery_schema_version"
            self.assertTrue(needs_discovery_reset(marker))

            marker.write_text(
                str(DISCOVERY_SCHEMA_VERSION - 1),
                encoding="utf-8",
            )
            self.assertTrue(needs_discovery_reset(marker))

            mark_discovery_schema(marker)
            self.assertFalse(needs_discovery_reset(marker))


if __name__ == "__main__":
    unittest.main()
