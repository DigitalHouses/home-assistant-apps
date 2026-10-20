"""Recorder-safe RPM trends: stable per-network sensor, cadence and gaps."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.discovery import (
    DISCOVERY, build_discovery, network_rpm_availability_topic, network_rpm_topic,
)
from zigbee_monitor.service import MonitorService

IEEE = "0x00158d0000000001"
NID = "z2m_00158d0000000001"
BASE = "zigbee2mqtt"


class PerNetworkRPMTrendTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = [600.0]
        self.sent = []
        self.store = ActivityStore(Path(tmp.name) / "activity.sqlite")
        self.addCleanup(self.store.close)
        self.net = {
            "network_id": NID, "base_topic": BASE, "name": BASE,
        }
        self.monitor = ZigbeeMonitor(parse_networks([self.net]))
        self.svc = MonitorService(
            self.monitor, self.store,
            publish=lambda topic, payload, retain: (
                self.sent.append((topic, payload, retain)) or True
            ),
            subscribe=lambda _: True,
            version="0.1.16", now=lambda: self.clock[0],
        )
        self.svc.connected()

    def msg(self, topic: str, value: bytes, *, retain=False, dup=False):
        return self.svc.receive(
            BASE + "/" + topic, value, retain=retain, dup=dup,
            observed_at=int(self.clock[0]),
        )

    def read(self, topic):
        return next(
            (value for key, value, _ in reversed(self.sent) if key == topic),
            None,
        )

    def online(self):
        self.msg("bridge/devices", json.dumps([{
            "ieee_address": IEEE, "type": "Router",
            "friendly_name": "Test", "definition": {"model": "Test"},
        }]).encode(), retain=True)
        self.msg("bridge/state", b"online", retain=True)

    def test_discovery_stable_scalar_identity_and_no_dynamic_attributes(self):
        components = build_discovery("0.1.16", self.monitor.networks)["components"]
        sensor = components[NID + "_rpm"]
        self.assertEqual(sensor["platform"], "sensor")
        self.assertEqual(
            sensor["default_entity_id"], "sensor.dh_zigbee_monitor_app_" + NID + "_rpm"
        )
        self.assertEqual(sensor["state_topic"], network_rpm_topic(NID))
        self.assertEqual(sensor["state_class"], "measurement")
        self.assertEqual(sensor["unit_of_measurement"], "messages/min")
        self.assertIn(BASE, sensor["name"])
        self.assertNotIn("json_attributes_topic", sensor)
        self.assertNotIn("json_attributes_template", sensor)
        self.assertEqual(len(sensor["availability"]), 2)
        self.assertIn(network_rpm_availability_topic(NID),
                      [x["topic"] for x in sensor["availability"]])

    def test_before_bridge_confirmation_is_unavailable_not_zero(self):
        self.assertEqual(self.read(network_rpm_availability_topic(NID)), "offline")
        self.assertIsNone(self.read(network_rpm_topic(NID)))
        self.online()
        self.assertEqual(self.read(network_rpm_availability_topic(NID)), "online")
        self.assertEqual(self.read(network_rpm_topic(NID)), "0.00")
        self.assertTrue(all(retain for _, _, retain in self.sent))

    def test_live_ui_is_10s_chart_is_only_one_sample_per_minute(self):
        self.online()
        topic = network_rpm_topic(NID)
        first = len([x for x in self.sent if x[0] == topic])
        for _ in range(3):
            self.msg("Test", b'{"temperature":24}')
        self.clock[0] = 621.0
        self.svc.tick()
        # Live tree rate has changed, but Recorder sensor stayed at 0 in
        # minute 10. This is intentional to limit Recorder to 1/minute.
        self.assertEqual(self.read(topic), "0.00")
        self.assertEqual(len([x for x in self.sent if x[0] == topic]), first)
        self.clock[0] = 661.0
        self.svc.tick()
        self.assertNotEqual(self.read(topic), "0.00")
        self.assertEqual(len([x for x in self.sent if x[0] == topic]), first + 1)

    def test_retained_and_mqtt_dup_packets_do_not_create_graph_spikes(self):
        self.online()
        for _ in range(10):
            self.msg("Test", b'{"temperature":25}', retain=True)
            self.msg("Test", b'{"temperature":25}', dup=True)
        self.clock[0] = 661.0
        self.svc.tick()
        self.assertEqual(self.read(network_rpm_topic(NID)), "0.00")

    def test_offline_and_reconnect_have_unavailable_gap(self):
        self.online()
        self.msg("Test", b'{"temperature":25}')
        self.msg("bridge/state", b"offline")
        self.assertEqual(self.read(network_rpm_availability_topic(NID)), "offline")
        self.clock[0] = 670.0
        self.svc.disconnected()
        self.svc.connected()
        self.assertEqual(self.read(network_rpm_availability_topic(NID)), "offline")
        self.msg("bridge/state", b"online", retain=True)
        self.assertEqual(self.read(network_rpm_availability_topic(NID)), "online")

    def test_multiple_networks_have_independent_stable_series(self):
        networks = parse_networks([
            self.net,
            {"network_id": "z2m_00158d0000000002",
             "base_topic": "zigbee2mqtt_office", "name": "Office"},
        ])
        c = build_discovery("0.1.16", networks)["components"]
        ids = [c[x + "_rpm"]["default_entity_id"]
               for x in (NID, "z2m_00158d0000000002")]
        self.assertEqual(len(set(ids)), 2)
        self.assertNotEqual(
            c[NID + "_rpm"]["state_topic"],
            c["z2m_00158d0000000002_rpm"]["state_topic"],
        )


if __name__ == "__main__":
    unittest.main()
