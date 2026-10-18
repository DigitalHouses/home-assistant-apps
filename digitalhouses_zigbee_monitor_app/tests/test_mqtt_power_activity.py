"""Zigbee2MQTT passive power inventory and genuine MQTT-activity regression tests.

No network polling, no invented online/offline status, and no new HA entities.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.discovery import state_topic, validity_topic
from zigbee_monitor.service import MonitorService


NETWORK = "floor_1"
BASE = "zigbee2mqtt"
DEVICES = [
    ("led_strip", "0xa4c138f16f1cc567", "Router", "Mains (single phase)", "GL-C-008P"),
    ("power_strip", "0xa4c138a24a271fab", "Router", "Mains (single phase)", "WP33-EU/WP34-EU"),
    ("th_bedroom", "0x30fb10fffe788014", "EndDevice", "Battery", "SNZB-02D"),
    ("tstat_livingroom", "0x54ef44100159df84", "Router", "DC Source", "UT-A01E"),
]


def inventory() -> bytes:
    return json.dumps([
        {
            "friendly_name": name, "ieee_address": ieee, "type": kind,
            "power_source": power, "definition": {"model": model, "vendor": "Vendor"},
        }
        for name, ieee, kind, power, model in DEVICES
    ]).encode()


class Transport:
    def __init__(self):
        self.published = []
        self.subscribed = []

    def publish(self, topic, payload, retain):
        self.published.append((topic, payload, retain))
        return True

    def subscribe(self, topic):
        self.subscribed.append(topic)
        return True

    def last(self, topic):
        results = [v for t, v, _ in self.published if t == topic]
        return results[-1] if results else None


class PowerActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "activity.sqlite"
        self.store = ActivityStore(self.path)
        self.addCleanup(self.store.close)
        self.monitor = ZigbeeMonitor(parse_networks([{
            "network_id": NETWORK, "base_topic": BASE, "name": "Дом",
        }]))
        self.transport = Transport()
        self.clock = [600.0]
        self.service = MonitorService(
            self.monitor, self.store, publish=self.transport.publish,
            subscribe=self.transport.subscribe, version="0.1.5",
            now=lambda: self.clock[0],
        )
        self.service.connected()
        self.service.receive(BASE + "/bridge/devices", inventory(), retain=True)
        self.service.receive(BASE + "/bridge/state", b"online", retain=True)

    def details(self):
        return json.loads(self.transport.last(state_topic("inventory_details")))

    def test_real_power_source_is_not_inferred_from_router_vs_enddevice(self):
        devices = {d["name"]: d for d in self.details()["devices"]}
        self.assertEqual(devices["led_strip"]["power_class"], "mains")
        self.assertEqual(devices["led_strip"]["power_source"], "Mains (single phase)")
        self.assertEqual(devices["power_strip"]["power_label"], "Сеть")
        self.assertEqual(devices["th_bedroom"]["power_class"], "battery")
        self.assertEqual(devices["th_bedroom"]["device_type"], "EndDevice")
        self.assertEqual(devices["tstat_livingroom"]["power_class"], "external")
        self.assertEqual(devices["tstat_livingroom"]["power_label"], "Внешнее питание")
        for d in devices.values():
            self.assertIsNone(d["last_mqtt_message_at"])
            self.assertEqual(d["availability"], "unknown")
        self.assertEqual(self.transport.last(validity_topic("offline")), "offline")

    def test_retained_and_duplicate_mqtt_never_mark_device_recent(self):
        name = "th_bedroom"
        topic = BASE + "/" + name
        self.service.receive(topic, b'{"temperature":19}', retain=True, observed_at=611)
        self.service.receive(topic, b'{"temperature":20}', dup=True, observed_at=615)
        self.assertEqual(self.monitor.mqtt_activity_snapshot(), {})
        self.assertEqual(self.details()["devices"][0]["last_mqtt_message_at"], None)
        self.clock[0] = 660.0
        self.service.tick()
        self.assertEqual(self.store.last_mqtt_messages(), {})
        self.assertEqual(self.transport.last(validity_topic("offline")), "offline")

    def test_new_mqtt_message_does_not_fake_online_or_offline(self):
        self.service.receive(
            BASE + "/th_bedroom", b'{"temperature":20}', observed_at=611,
        )
        self.assertEqual(self.monitor.mqtt_activity_snapshot()[
            (NETWORK, DEVICES[2][1])
        ], 611)
        # Activity timestamps are aggregated and republished once per minute.
        self.clock[0] = 660.0
        self.service.tick()
        d = {x["name"]: x for x in self.details()["devices"]}["th_bedroom"]
        self.assertEqual(d["last_mqtt_message_at"], "1970-01-01T00:10:11+00:00")
        self.assertEqual(d["availability"], "unknown")
        self.assertEqual(d["availability_reason"], "availability_not_reported")
        self.assertEqual(self.transport.last(validity_topic("offline")), "offline")
        self.assertEqual(self.store.last_mqtt_messages()[(NETWORK, DEVICES[2][1])], 611)

    def test_last_mqtt_time_is_durable_across_process_restarts(self):
        self.service.receive(BASE + "/led_strip", b"{}", observed_at=620)
        self.clock[0] = 660.0
        self.service.tick()
        self.store.close()
        with ActivityStore(self.path) as reopened:
            self.assertEqual(reopened.last_mqtt_messages()[(NETWORK, DEVICES[0][1])], 620)

    def test_recorder_numeric_sensors_remain_without_dynamic_json_attributes(self):
        from zigbee_monitor.discovery import HISTORY, build_discovery
        comps = build_discovery("0.1.5")["components"]
        for key in HISTORY:
            self.assertNotIn("json_attributes_topic", comps[key])
        self.assertIn("json_attributes_topic", comps["inventory_details"])
        self.assertEqual(self.transport.last(validity_topic("offline")), "offline")


if __name__ == "__main__":
    unittest.main()
