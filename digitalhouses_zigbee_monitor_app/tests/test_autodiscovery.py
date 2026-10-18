"""Passive Zigbee2MQTT discovery and stable identity regression tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zigbee_monitor import ActivityStore, ZigbeeMonitor
from zigbee_monitor.autodiscovery import (
    DISCOVERY_FILTERS, discovery_from_bridge,
)
from zigbee_monitor.discovery import ROOT, state_topic, validity_topic
from zigbee_monitor.service import MonitorService

COORD_A = "0x00124b0022aabbcc"
COORD_B = "0x00124b0022aabbdd"
DEVICE = "0x00158d000100aabb"


def inventory(coordinator=COORD_A, name="Plug"):
    return json.dumps([
        {"type": "Coordinator", "ieee_address": coordinator,
         "friendly_name": "Coordinator", "definition": None},
        {"type": "Router", "ieee_address": DEVICE, "friendly_name": name,
         "definition": {"model": "ABC", "vendor": "Acme"}},
    ]).encode()


def info(coordinator=COORD_A):
    return json.dumps({
        "version": "2.0", "coordinator": {"ieee_address": coordinator},
        "network": {"channel": 11},
    }).encode()


class FakeTransport:
    def __init__(self):
        self.subscriptions = []
        self.messages = []

    def subscribe(self, topic):
        self.subscriptions.append(topic)
        return True

    def publish(self, topic, payload, retain):
        self.messages.append((topic, payload, retain))
        return True

    def latest(self, topic):
        for t, payload, _ in reversed(self.messages):
            if t == topic:
                return payload
        return None


class DiscoveryTests(unittest.TestCase):
    def test_retained_devices_are_authoritative_discovery_fallback(self):
        d = discovery_from_bridge("zigbee2mqtt_1/bridge/devices", inventory())
        self.assertEqual(d.base_topic, "zigbee2mqtt_1")
        self.assertEqual(d.coordinator_ieee, COORD_A)

    def test_bridge_info_and_nested_prefix(self):
        d = discovery_from_bridge("house/upper/bridge/info", info())
        self.assertEqual(d.base_topic, "house/upper")
        self.assertIn("+/bridge/info", DISCOVERY_FILTERS)
        self.assertIn("+/+/bridge/devices", DISCOVERY_FILTERS)

    def test_rogue_or_unvalidated_topics_do_not_create_network(self):
        samples = [
            ("zigbee2mqtt_1/bridge/state", b'{"state":"online"}'),
            ("sensors/bridge/devices", json.dumps([{"type": "Router", "ieee_address": DEVICE}]).encode()),
            ("random/bridge/info", b'{"coordinator":{"ieee_address":"not ieee"}}'),
            ("DigitalHouses/bridge/devices", inventory()),
            ("homeassistant/bridge/devices", inventory()),
            ("a/b/c/d/bridge/devices", inventory()),
            ("house/bridge/devices", b'{"type":"Coordinator"}'),
            ("house/bridge/devices", b"not json"),
            ("house/bridge/devices", json.dumps([
                {"type": "Coordinator", "ieee_address": COORD_A},
                {"type": "Coordinator", "ieee_address": COORD_B},
            ]).encode()),
        ]
        for topic, payload in samples:
            with self.subTest(topic=topic, payload=payload):
                self.assertIsNone(discovery_from_bridge(topic, payload))


class ServiceDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "activity.sqlite"
        self.store = ActivityStore(self.path)
        self.addCleanup(self.store.close)
        self.t = FakeTransport()
        self.clock = [3600.0]
        self.service = MonitorService(
            ZigbeeMonitor(()), self.store,
            subscribe=self.t.subscribe, publish=self.t.publish,
            version="0.1.1", now=lambda: self.clock[0],
        )

    def test_zero_networks_is_unknown_not_false_zero(self):
        self.service.connected()
        self.assertIsNone(self.t.latest(state_topic("networks")))
        self.assertEqual(self.t.latest(validity_topic("networks")), "offline")
        self.assertIn("+/bridge/devices", self.t.subscriptions)
        self.assertIn("+/bridge/info", self.t.subscriptions)
        self.assertNotIn("#", self.t.subscriptions)

    def test_automatically_find_two_networks_and_keep_device_history(self):
        self.service.connected()
        self.assertEqual(
            self.service.receive("zigbee2mqtt_1/bridge/devices", inventory(), retain=True),
            "inventory",
        )
        self.assertEqual(self.t.latest(state_topic("networks")), "1")
        self.assertIn("zigbee2mqtt_1/#", self.t.subscriptions)
        self.assertEqual(self.store.known_networks()[0].network_id, "z2m_" + COORD_A[2:])
        self.service.receive("zigbee2mqtt_2/bridge/info", info(COORD_B), retain=True)
        self.service.receive("zigbee2mqtt_2/bridge/devices", inventory(COORD_B), retain=True)
        self.assertEqual(self.t.latest(state_topic("networks")), "2")
        self.assertEqual(len(self.service.monitor.networks), 2)
        self.service.receive("zigbee2mqtt_1/bridge/state", b"online", retain=True)
        self.service.receive("zigbee2mqtt_2/bridge/state", b"online", retain=True)
        self.service.receive("zigbee2mqtt_1/Plug", b'{"state":"ON"}', observed_at=3600)
        self.clock[0] = 3660
        self.service.tick()
        self.assertEqual(self.store.sum_messages(from_epoch=3600, until_epoch=3660), 1)

    def test_rename_base_topic_preserves_ieee_and_minute_history(self):
        self.service.connected()
        self.service.receive("zigbee2mqtt_1/bridge/devices", inventory(), retain=True)
        nid = self.service.monitor.networks[0].network_id
        self.service.receive("zigbee2mqtt_1/Plug", b"{}", observed_at=3600)
        self.clock[0] = 3660
        self.service.tick()
        self.service.receive("zigbee2mqtt_new/bridge/info", info(), retain=True)
        self.assertEqual(self.service.monitor.networks[0].network_id, nid)
        self.assertEqual(self.service.monitor.networks[0].base_topic, "zigbee2mqtt_new")
        self.service.receive("zigbee2mqtt_new/bridge/devices", inventory(name="Renamed"), retain=True)
        self.service.receive("zigbee2mqtt_new/Renamed", b"{}", observed_at=3660)
        self.clock[0] = 3720
        self.service.tick()
        rows = self.store.top(from_epoch=3600, until_epoch=3720)
        self.assertEqual(rows[0]["messages"], 2)
        self.assertEqual(rows[0]["name"], "Renamed")
        self.assertEqual(self.store.known_networks()[0].network_id, nid)

    def test_registered_networks_survive_reopen_without_new_config(self):
        self.service.connected()
        self.service.receive("zigbee2mqtt_usb/bridge/devices", inventory(), retain=True)
        previous = self.store.known_networks()
        self.store.close()
        with ActivityStore(self.path) as reopened:
            self.assertEqual(reopened.known_networks(), previous)
            self.assertEqual(reopened.known_networks()[0].base_topic, "zigbee2mqtt_usb")

    def test_no_accidental_invented_network_on_unrelated_mqtt(self):
        self.service.connected()
        self.service.receive("homeassistant/sensor/foo/config", b"{}")
        self.service.receive("other/bridge/state", b'{"state":"online"}')
        self.assertEqual(self.service.monitor.networks, ())
        self.assertEqual(self.t.latest(validity_topic("devices")), "offline")

    def test_refresh_zero_discovery_times_out_instead_of_false_success(self):
        self.service.connected()
        self.service.receive(ROOT + "/command/refresh", b"PRESS")
        self.assertIn("+/bridge/devices", self.t.subscriptions)
        self.clock[0] += 16
        self.service.tick()
        card = json.loads(self.t.latest(state_topic("card")))
        self.assertEqual(card["state"], "error")

    def test_coordinator_replacement_does_not_silently_reuse_identity(self):
        self.service.connected()
        self.service.receive("zigbee2mqtt_usb/bridge/devices", inventory(), retain=True)
        with self.assertRaisesRegex(ValueError, "coordinator changed"):
            self.service.receive("zigbee2mqtt_usb/bridge/info", info(COORD_B), retain=True)
        self.assertEqual(len(self.service.monitor.networks), 1)


if __name__ == "__main__":
    unittest.main()
