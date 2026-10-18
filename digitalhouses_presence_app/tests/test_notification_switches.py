"""Persisted MQTT notification switches do not affect evidence or event delivery."""
import json
import queue
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from dh_presence.notifications import NotificationSelection, DEFAULTS, NOTIFICATION_KEYS
from dh_presence.discovery import discovery, topic
from dh_presence.zones import zone_key
from dh_presence.core import Engine, Status
from app import MqttOutput, publish_snapshot


class FakeOutput:
    def __init__(self):
        self.calls = []
    def publish(self, where, data, **kwargs):
        self.calls.append((where, data))
        return True


class NotificationSwitchTests(unittest.TestCase):
    def test_defaults_and_persisted_overrides_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "notification.json")
            first = NotificationSelection(path)
            self.assertEqual(first.enabled, {"gps": False, "wifi": False})
            first.sync_zones({"zone.home": "Дом"})
            self.assertEqual(first.mqtt_state("zones/" + zone_key("zone.home")), "OFF")
            self.assertTrue(first.change("gps", "ON"))
            self.assertTrue(first.change("wifi", "ON"))
            self.assertTrue(first.change("zones/" + zone_key("zone.home"), "ON"))
            again = NotificationSelection(path)
            self.assertEqual(again.enabled, {"gps": True, "wifi": True})
            self.assertEqual(json.loads(Path(path).read_text())["schema_version"], 2)
            self.assertEqual(again.mqtt_state("zones/" + zone_key("zone.home")), "ON")
            self.assertEqual(again.mqtt_state("wifi"), "ON")

    def test_invalid_or_corrupt_settings_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            s = NotificationSelection(str(path))
            for key, state in (("wrong", "ON"), ("gps", "off"), ("wifi", "TRUE")):
                with self.subTest(key=key, state=state), self.assertRaises(ValueError):
                    s.change(key, state)
            self.assertEqual(s.enabled, DEFAULTS)
            path.write_text('{"schema_version":1,"enabled":{"gps":"ON"}}')
            with self.assertRaises(ValueError):
                NotificationSelection(str(path))

    def test_mqtt_discovery_switches_share_device_and_use_no_retained_commands(self):
        cfg = discovery("0.1.27", [], {"zone.home": "Дом"})
        self.assertEqual(cfg["device"]["identifiers"], ["dh_presence_app"])
        self.assertNotIn("notify_presence", cfg["components"])
        zone = cfg["components"]["notify_zone_" + zone_key("zone.home")]
        self.assertEqual(zone["command_topic"], topic("notifications/zones/" + zone_key("zone.home") + "/set"))
        for key in NOTIFICATION_KEYS:
            c = cfg["components"]["notify_" + key]
            self.assertEqual(c["platform"], "switch")
            self.assertEqual(c["unique_id"], "dh_presence_app_notify_" + key)
            self.assertEqual(c["default_entity_id"], "switch.dh_presence_app_notify_" + key)
            self.assertEqual(c["command_topic"], topic("notifications/" + key + "/set"))
            self.assertEqual(c["state_topic"], topic("notifications/" + key + "/state"))
            self.assertEqual(c["payload_on"], "ON")
            self.assertEqual(c["payload_off"], "OFF")
            self.assertFalse(c["retain"])

    def test_mqtt_command_ignores_retained_and_invalid_payload(self):
        output = object.__new__(MqttOutput)
        output.notification_commands = queue.SimpleQueue()
        output.mode_commands = queue.SimpleQueue()
        output.operation_commands = queue.SimpleQueue()
        output.discovery_requests = queue.SimpleQueue()
        def incoming(key, value, retained=False):
            msg = SimpleNamespace(topic=topic("notifications/" + key + "/set"),
                                  payload=value, retain=retained)
            MqttOutput._message(output, None, None, msg)
        incoming("gps", b"ON", True)
        incoming("gps", b"on")
        incoming("gps", b"garbage")
        self.assertTrue(output.notification_commands.empty())
        incoming("gps", b"ON")
        incoming("wifi", b"OFF")
        incoming("zones/" + zone_key("zone.home"), b"ON")
        self.assertEqual(output.notification_commands.get_nowait(), ("gps", "ON"))
        self.assertEqual(output.notification_commands.get_nowait(), ("wifi", "OFF"))
        self.assertEqual(output.notification_commands.get_nowait(), ("zones/" + zone_key("zone.home"), "ON"))
        self.assertTrue(output.notification_commands.empty())

    def test_snapshot_publishes_all_switch_states_without_suppressing_presence(self):
        e = Engine()
        e.add("device_tracker.iphone", "iPhone")
        e.gps_observation("device_tracker.iphone", Status.HOME,
                          datetime.now(timezone.utc))
        with tempfile.TemporaryDirectory() as tmp:
            pref = NotificationSelection(str(Path(tmp) / "n.json"))
            pref.sync_zones({"zone.home": "Дом"})
            output = FakeOutput()
            with patch("app.publish_controls", return_value=True):
                self.assertTrue(publish_snapshot(output, e, "0.1.18", "2026-10-16T00:00:00+00:00",
                                                 None, None, pref, {"zone.home": "Дом"}))
            topics = dict(output.calls)
            self.assertEqual(topics[topic("notifications/zones/" + zone_key("zone.home") + "/state")], "OFF")
            self.assertEqual(topics[topic("notifications/gps/state")], "OFF")
            self.assertEqual(topics[topic("notifications/wifi/state")], "OFF")
            self.assertEqual(topics[topic("state")]["status"], "home")
            self.assertEqual(topics[topic("availability")], "online")


if __name__ == "__main__":
    unittest.main()
