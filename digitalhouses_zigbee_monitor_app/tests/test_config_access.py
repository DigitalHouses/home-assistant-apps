"""Test no-secret, read-only HA config diagnostics and MQTT HA exposure."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.config_access import probe_config_access
from zigbee_monitor.discovery import DISCOVERY, ROOT, state_topic
from zigbee_monitor.service import MonitorService


class ConfigAccessFilesystemTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "homeassistant"

    def probe(self):
        return probe_config_access(self.root, is_mount=lambda _: True)

    def test_no_mount(self):
        self.assertEqual(self.probe(), {
            "state": "mount_missing",
            "mount": "missing",
            "z2m_directory": "not_checked",
            "z2m_config": "not_checked",
        })

    def test_directory_exists_but_not_mounted(self):
        self.root.mkdir()
        result = probe_config_access(self.root, is_mount=lambda _: False)
        self.assertEqual(result["state"], "mount_missing")

    def test_zigbee2mqtt_directory_missing(self):
        self.root.mkdir()
        result = self.probe()
        self.assertEqual(result["state"], "directory_missing")
        self.assertEqual(result["mount"], "ok")
        self.assertEqual(result["z2m_directory"], "missing")

    def test_zigbee2mqtt_file_missing(self):
        (self.root / "zigbee2mqtt").mkdir(parents=True)
        result = self.probe()
        self.assertEqual(result["state"], "file_missing")
        self.assertEqual(result["z2m_config"], "missing")

    def test_existing_config_is_openable_without_reading_or_logging_secrets(self):
        z2m = self.root / "zigbee2mqtt"
        z2m.mkdir(parents=True)
        text = "mqtt:\n  password: PRIVATE_MQTT_PASSWORD\nadvanced:\n  network_key: SECRET_KEY\n"
        path = z2m / "configuration.yaml"
        path.write_text(text)
        with patch("builtins.open", side_effect=AssertionError("must not read YAML")):
            result = self.probe()
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["mount"], "ok")
        self.assertEqual(result["z2m_directory"], "ok")
        self.assertEqual(result["z2m_config"], "readable")
        self.assertNotIn("PRIVATE_MQTT_PASSWORD", json.dumps(result))
        self.assertNotIn("SECRET_KEY", json.dumps(result))
        self.assertEqual(path.read_text(), text)

    def test_symlink_does_not_escape_mount(self):
        z2m = self.root / "zigbee2mqtt"
        z2m.mkdir(parents=True)
        target = self.root.parent / "unrelated_secret"
        target.write_text("SENSITIVE")
        (z2m / "configuration.yaml").symlink_to(target)
        status = self.probe()
        self.assertEqual(status["state"], "file_unreadable")
        self.assertEqual(status["z2m_config"], "not_readable")
        self.assertNotIn("SENSITIVE", json.dumps(status))

    def test_permission_denied_is_not_exposed_in_diagnostics(self):
        path = self.root / "zigbee2mqtt"
        path.mkdir(parents=True)
        (path / "configuration.yaml").write_text("password: TOP_SECRET")
        with patch("zigbee_monitor.config_access.os.open", side_effect=PermissionError("TOP_SECRET")):
            status = self.probe()
        self.assertEqual(status["state"], "file_unreadable")
        self.assertNotIn("TOP_SECRET", json.dumps(status))


class ConfigAccessMQTTTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = ActivityStore(Path(temp.name) / "activity.sqlite")
        self.addCleanup(self.store.close)
        self.sent = []
        self.service = MonitorService(
            ZigbeeMonitor(()), self.store,
            publish=lambda topic, body, retain: (self.sent.append((topic, body, retain)) or True),
            subscribe=lambda _: True, version="0.1.14", now=lambda: 1234567890.0,
        )

    def last(self, topic):
        return next((body for key, body, _ in reversed(self.sent) if key == topic), None)

    def test_sensor_is_stable_and_diagnostic_only(self):
        result = {"state": "file_missing", "mount": "ok",
                  "z2m_directory": "ok", "z2m_config": "missing"}
        self.service.set_config_access(result)
        self.service.connected()
        discovery = json.loads(self.last(DISCOVERY))["components"]["config_access"]
        self.assertEqual(discovery["platform"], "sensor")
        self.assertEqual(discovery["entity_category"], "diagnostic")
        self.assertEqual(discovery["default_entity_id"],
                         "sensor.dh_zigbee_monitor_app_config_access")
        self.assertEqual(discovery["state_topic"], state_topic("config_access"))
        self.assertNotIn("command_topic", discovery)
        initial = json.loads(self.last(state_topic("config_access")))
        self.assertEqual(initial, result)
        self.service.set_config_access({
            "state": "ready", "mount": "ok",
            "z2m_directory": "ok", "z2m_config": "readable",
        })
        self.assertEqual(json.loads(self.last(state_topic("config_access")))["state"],
                         "ready")
        self.assertTrue(all(retain for _, _, retain in self.sent))

    def test_unexpected_fields_or_secret_text_are_never_published(self):
        self.service.connected()
        self.service.set_config_access({
            "state": "ready", "mount": "ok",
            "z2m_directory": "ok", "z2m_config": "readable",
            "password": "DO_NOT_PUBLISH",
            "file_contents": "network_key: DO_NOT_PUBLISH",
        })
        self.assertNotIn("DO_NOT_PUBLISH", json.dumps(self.sent))
        with self.assertRaises(ValueError):
            self.service.set_config_access({
                "state": "password: DO_NOT_PUBLISH", "mount": "ok",
                "z2m_directory": "ok", "z2m_config": "readable",
            })


if __name__ == "__main__":
    unittest.main()
