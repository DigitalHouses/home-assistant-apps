"""Per-network offline Recorder series: discovery, trust and history isolation."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.discovery import (
    DISCOVERY, ROOT, build_discovery,
    network_offline_availability_topic, network_offline_topic, state_topic,
)
from zigbee_monitor.service import MonitorService

N1 = "z2m_00158d0000000001"
N2 = "z2m_00158d0000000002"
IEEE_A = "0x00158d0000000011"
IEEE_B = "0x00158d0000000012"
IEEE_C = "0x00158d0000000021"
APP = Path(__file__).resolve().parents[1]


class OfflineHistoryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = [600.0]
        self.sent = []
        self.store = ActivityStore(Path(tmp.name) / "state.sqlite")
        self.addCleanup(self.store.close)
        self.monitor = ZigbeeMonitor(parse_networks([
            {"network_id": N1, "name": "zigbee2mqtt_1", "base_topic": "z2m_1"},
            {"network_id": N2, "name": "zigbee2mqtt_2", "base_topic": "z2m_2"},
        ]))
        self.service = MonitorService(
            self.monitor, self.store,
            publish=lambda topic, payload, retained: (
                self.sent.append((topic, payload, retained)) or True
            ),
            subscribe=lambda _: True,
            version="0.1.21", now=lambda: self.clock[0],
        )
        self.service.connected()

    def publish(self, base, topic, payload, retain=True):
        value = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return self.service.receive(
            base + "/" + topic, value, retain=retain,
            observed_at=int(self.clock[0]),
        )

    def inventory(self, base, devices):
        self.publish(base, "bridge/devices", [
            {"ieee_address": ieee, "friendly_name": name, "type": "Router"}
            for ieee, name in devices
        ])
        self.publish(base, "bridge/state", b"online")

    def last(self, topic):
        return next((value for t, value, _ in reversed(self.sent) if t == topic), None)

    def count(self, topic):
        return sum(t == topic for t, _, _ in self.sent)

    def test_discovery_uses_stable_numeric_recorder_sensors(self):
        components = build_discovery("0.1.21", self.monitor.networks)["components"]
        for nid, name in [(N1, "zigbee2mqtt_1"), (N2, "zigbee2mqtt_2")]:
            component = components[nid + "_offline"]
            self.assertEqual(component["platform"], "sensor")
            self.assertEqual(component["default_entity_id"],
                             "sensor.dh_zigbee_monitor_app_" + nid + "_offline")
            self.assertEqual(component["unique_id"],
                             "dh_zigbee_monitor_app_" + nid + "_offline")
            self.assertIn(name, component["name"])
            self.assertEqual(component["state_class"], "measurement")
            self.assertEqual(component["state_topic"], network_offline_topic(nid))
            self.assertIn(network_offline_availability_topic(nid),
                          [x["topic"] for x in component["availability"]])
            self.assertEqual(component["availability_mode"], "all")
            self.assertNotIn("json_attributes_topic", component)
            self.assertNotIn("json_attributes_template", component)
        self.assertNotEqual(network_offline_topic(N1), network_offline_topic(N2))

    def test_positive_offline_lower_bound_and_unknown_only_gap(self):
        n1_data = network_offline_topic(N1)
        n1_valid = network_offline_availability_topic(N1)
        self.assertIsNone(self.last(n1_data))
        self.assertEqual(self.last(n1_valid), "offline")
        self.inventory("z2m_1", [(IEEE_A, "Device_A"), (IEEE_B, "Device_B")])
        # Bridge is healthy but availability is still incomplete.
        self.assertEqual(self.last(n1_valid), "offline")
        self.assertIsNone(self.last(n1_data))

        self.publish("z2m_1", "Device_A/availability", {"state": "offline"})
        self.assertEqual(self.last(n1_data), "1")
        self.assertEqual(self.last(n1_valid), "online")
        snapshot = json.loads(self.last(state_topic("networks_details")))
        self.assertEqual(snapshot["networks"][0]["offline"], 1)

        self.publish("z2m_1", "Device_A/availability", {"state": "online"})
        self.assertEqual(self.last(n1_valid), "offline",
                         "Unknown peer prevents a false 0")
        self.assertEqual(self.last(n1_data), "1",
                         "Retained prior value stays hidden via availability")

        self.publish("z2m_1", "Device_B/availability", {"state": "online"})
        self.assertEqual(self.last(n1_data), "0")
        self.assertEqual(self.last(n1_valid), "online")

    def test_network_history_is_independent_of_other_z2m(self):
        self.inventory("z2m_1", [(IEEE_A, "Device_A")])
        self.inventory("z2m_2", [(IEEE_C, "Device_C")])
        self.publish("z2m_1", "Device_A/availability", {"state": "offline"})
        self.assertEqual(self.last(network_offline_topic(N1)), "1")
        self.assertEqual(self.last(network_offline_availability_topic(N1)), "online")
        self.assertEqual(self.last(network_offline_availability_topic(N2)), "offline")
        self.publish("z2m_2", "Device_C/availability", {"state": "online"})
        self.assertEqual(self.last(network_offline_topic(N2)), "0")
        self.assertEqual(self.last(network_offline_availability_topic(N2)), "online")
        # The already existing global total agrees with per-network counts.
        self.assertEqual(self.last(state_topic("offline")), "1")

        self.publish("z2m_1", "bridge/state", b"offline", retain=False)
        self.assertEqual(self.last(network_offline_availability_topic(N1)), "offline")
        self.assertEqual(self.last(network_offline_availability_topic(N2)), "online")
        self.assertEqual(self.last(state_topic("offline")) is not None, True)

    def test_idempotent_publication_and_reconnect_gap(self):
        self.inventory("z2m_1", [(IEEE_A, "Device_A")])
        self.publish("z2m_1", "Device_A/availability", {"state": "offline"})
        topic = network_offline_topic(N1)
        before = self.count(topic)
        for _ in range(5):
            self.service._publish_networks()
        self.assertEqual(self.count(topic), before)
        self.service.disconnected()
        self.service.connected()
        self.assertEqual(self.last(network_offline_availability_topic(N1)), "offline")
        self.assertNotEqual(self.last(network_offline_availability_topic(N1)), "online")
        # Recovery must be earned by new observations, not stale retained data.

    def test_dynamic_graph_includes_total_and_all_networks(self):
        graph = yaml.safe_load((APP / "examples/lovelace/"
                       "dh_zigbee_monitor_app_offline_trends_ru.yaml").read_text())
        self.assertEqual(graph["type"], "custom:auto-entities")
        self.assertEqual(graph["card"]["type"], "history-graph")
        include = graph["filter"]["include"]
        self.assertIn({"entity_id": "sensor.dh_zigbee_monitor_app_offline",
                       "options": {"name": "ИТОГО"}}, include)
        self.assertIn({"entity_id": "sensor.dh_zigbee_monitor_app_*_offline"}, include)
        self.assertNotIn("exclude", graph["filter"])
        package = yaml.safe_load((APP / "examples/packages/"
                       "dh_zigbee_monitor_app_global_package.yaml").read_text())
        globs = package["dh_zigbee_monitor_app_global_package"]["recorder"]["include"]["entity_globs"]
        self.assertIn("sensor.dh_zigbee_monitor_app_*_offline", globs)


if __name__ == "__main__":
    unittest.main()
