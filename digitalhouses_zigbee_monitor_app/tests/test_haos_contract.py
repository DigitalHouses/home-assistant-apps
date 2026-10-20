"""HAOS package, MQTT runtime consent, and telemetry policy-v2 regressions."""
from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from zigbee_monitor.discovery import ROOT, build_discovery
from zigbee_monitor.telemetry import TelemetryClient

APP_DIR = Path(__file__).resolve().parents[1]
REPO = APP_DIR.parent


class TransportStub:
    def __init__(self, status: int = 204):
        self.status = status
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.status


class PackageTests(unittest.TestCase):
    def test_package_identity_and_immutable_image(self):
        config = yaml.safe_load((APP_DIR / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(config["slug"], "digitalhouses_zigbee_monitor_app")
        self.assertEqual(config["name"], "DigitalHouses Zigbee Monitor App")
        self.assertEqual(config["version"], "0.1.16")
        self.assertEqual(config["stage"], "experimental")
        self.assertEqual(config["image"], "ghcr.io/digitalhouses/digitalhouses_zigbee_monitor_app")
        self.assertEqual(config["services"], ["mqtt:need"])
        self.assertFalse(config["options"]["telemetry_enabled"])
        self.assertNotIn("zigbee2mqtt", config["options"])
        self.assertNotIn("zigbee2mqtt", config["schema"])
        self.assertEqual(config["options"]["coordinators"], [])
        self.assertEqual(config["options"]["repeaters"], [])
        self.assertIn("NET_RAW", config["privileged"])
        # Read-only and narrowly scoped mount: no access to Supervisor's
        # private storage of other Apps, no elevated role and no host FS.
        self.assertEqual(config["map"], [{
            "type": "homeassistant_config",
            "read_only": True,
            "path": "/homeassistant",
        }])
        self.assertEqual(config["hassio_role"], "default")
        self.assertNotIn("full_access", config)

    def test_store_images_have_valid_geometry(self):
        for name, expected in (("icon.png", (128, 128)), ("logo.png", (250, 100))):
            data = (APP_DIR / name).read_bytes()
            self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(struct.unpack(">II", data[16:24]), expected)

    def test_run_script_requires_supervisor_mqtt(self):
        script = (APP_DIR / "rootfs/run.sh").read_text(encoding="utf-8")
        self.assertIn("bashio::services mqtt host", script)
        self.assertIn("MQTT_HOST", script)
        self.assertIn("MQTT_PASSWORD", script)
        self.assertNotIn("mosquitto_pub", script)

    def test_discovery_has_no_telemetry_device_inventory(self):
        components = build_discovery("0.1.0")["components"]
        self.assertEqual(
            components["delete_telemetry"]["command_topic"],
            ROOT + "/command/delete_telemetry",
        )
        self.assertNotIn("json_attributes_topic", components["offline"])
        self.assertNotIn("spammers", components)

    def test_consent_is_mandatory_before_runtime(self):
        # Rejected consent must exit before any SQLite or telemetry identity is created.
        with patch("app.read_options", return_value={
            "zigbee2mqtt": [{"network_id": "main", "base_topic": "z2m", "name": "Main"}],
            "telemetry_enabled": False,
            "log_level": "info",
        }), patch("app.ActivityStore") as store, patch("app.TelemetryClient") as telemetry:
            from app import Application
            with self.assertRaises(SystemExit) as ctx:
                Application()
            self.assertEqual(ctx.exception.code, 1)
            store.assert_not_called()
            telemetry.assert_not_called()


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "telemetry.json"

    def test_policy_v2_payload_only_allowed_fields(self):
        transport = TransportStub()
        client = TelemetryClient(
            enabled=True, version="0.1.0",
            state_file=self.path, transport=transport, now_epoch=lambda: 1000.0,
        )
        self.assertEqual(set(client.payload()), {
            "schema", "telemetry_policy_version", "installation_id", "product", "version"
        })
        self.assertEqual(client.payload()["telemetry_policy_version"], 2)
        self.assertEqual(client.payload()["product"], "digitalhouses_zigbee_monitor_app")
        self.assertTrue(client.tick())
        self.assertEqual(transport.calls[0]["path"], "/v1/heartbeat")
        self.assertEqual(transport.calls[0]["payload"], client.payload())
        self.assertTrue(self.path.exists())
        self.assertEqual(len(bytes.fromhex(client.installation_token)), 32)

    def test_failed_telemetry_transport_does_not_break_monitoring(self):
        class BrokenTransport:
            def request(self, **kwargs):
                raise OSError("no route")
        client = TelemetryClient(
            enabled=True, version="0.1.0",
            state_file=self.path, transport=BrokenTransport(), now_epoch=lambda: 1000.0,
        )
        self.assertFalse(client.tick())

    def test_deletion_rotates_installation_id_and_token(self):
        transport = TransportStub()
        client = TelemetryClient(
            enabled=True, version="0.1.0",
            state_file=self.path, transport=transport, now_epoch=lambda: 1000.0,
        )
        old_id, old_token = client.installation_id, client.installation_token
        self.assertTrue(client.delete())
        self.assertEqual(transport.calls[-1]["path"], "/v1/installation")
        self.assertNotEqual(client.installation_id, old_id)
        self.assertNotEqual(client.installation_token, old_token)
        restored = TelemetryClient(
            enabled=True, version="0.1.0",
            state_file=self.path, transport=transport, now_epoch=lambda: 1000.0,
        )
        self.assertEqual(restored.installation_id, client.installation_id)
        self.assertEqual(restored.installation_token, client.installation_token)


if __name__ == "__main__":
    unittest.main()
