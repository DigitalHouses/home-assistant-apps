"""Per-network HA MQTT Discovery settings and confirmed Problem transitions."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.discovery import ROOT, DISCOVERY, EVENT_TOPIC, build_discovery
from zigbee_monitor.problems import TrafficDetector, network_problems
from zigbee_monitor.service import MonitorService

IEEE1 = "0x00158d0000000001"
IEEE2 = "0x00158d0000000002"


class Transport:
    def __init__(self):
        self.out = []

    def publish(self, topic, payload, retain):
        self.out.append((topic, payload, retain))
        return True

    def subscribe(self, topic):
        return True

    def last(self, topic):
        for t, body, _ in reversed(self.out):
            if t == topic:
                return body
        return None

    def events(self):
        return [json.loads(body) for topic, body, _ in self.out if topic == EVENT_TOPIC]


class NetworkProblemsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "activity.sqlite"
        self.store = ActivityStore(self.path)
        self.addCleanup(self.store.close)
        self.clock = [10000.0]
        self.t = Transport()
        self.s = MonitorService(
            ZigbeeMonitor(parse_networks([
                {"network_id": "main", "base_topic": "z2m", "name": "Main"},
                {"network_id": "second", "base_topic": "zigbee/second", "name": "Second"},
            ])), self.store, publish=self.t.publish, subscribe=self.t.subscribe,
            version="0.1.8", now=lambda: self.clock[0],
        )
        self.s.connected()
        self.s.receive("z2m/bridge/devices", json.dumps([
            {"type": "Router", "ieee_address": IEEE1, "friendly_name": "plug"},
            {"type": "EndDevice", "ieee_address": IEEE2, "friendly_name": "sensor"},
        ]).encode(), retain=True)
        self.s.receive("z2m/bridge/state", b"online", retain=True)

    def status(self, network, kind):
        return self.t.last(f"{ROOT}/problems/{network}/{kind}/state")

    def validity(self, network, kind):
        return self.t.last(f"{ROOT}/problems/{network}/{kind}/valid")

    def aggregate(self):
        return json.loads(self.t.last(f"{ROOT}/problems/presentation"))

    def test_dynamic_discovery_has_three_problem_entities_and_ha_controls(self):
        payload = json.loads(self.t.last(DISCOVERY))
        components = payload["components"]
        for n in ("main", "second"):
            for kind in ("bridge_offline", "devices_offline", "mqtt_traffic_low"):
                comp = components[f"{n}_{kind}_problem"]
                self.assertEqual(comp["device_class"], "problem")
                self.assertEqual(comp["platform"], "binary_sensor")
                self.assertEqual(comp["availability_mode"], "all")
                self.assertIn("/valid", comp["availability"][1]["topic"])
            self.assertEqual(components[f"{n}_rpm_auto"]["platform"], "switch")
            self.assertEqual(components[f"{n}_rpm_threshold"]["platform"], "number")
        self.assertEqual(components["problems"]["default_entity_id"],
                         "sensor.dh_zigbee_monitor_app_problems")
        self.assertEqual(self.t.last(f"{ROOT}/settings/main/rpm_auto/state"), "ON")
        self.assertEqual(self.t.last(f"{ROOT}/settings/main/rpm_threshold/state"), "10")

    def test_bridge_and_device_problems_publish_change_immediately(self):
        self.assertEqual(self.status("main", "bridge_offline"), "OFF")
        self.assertEqual(self.validity("main", "devices_offline"), "offline")
        self.s.receive("z2m/plug/availability", b'{"state":"online"}', retain=True)
        self.s.receive("z2m/sensor/availability", b'{"state":"online"}', retain=True)
        self.assertEqual(self.status("main", "devices_offline"), "OFF")
        self.s.receive("z2m/plug/availability", b'{"state":"offline"}')
        self.assertEqual(self.status("main", "devices_offline"), "ON")
        self.assertEqual(self.aggregate()["active"][0]["problem_id"],
                         "main:devices_offline")
        self.assertIn("device_offline", [e["event_type"] for e in self.t.events()])
        self.assertNotIn("problem_started", [e["event_type"] for e in self.t.events()])
        self.s.receive("z2m/plug/availability", b'{"state":"online"}')
        self.assertEqual(self.status("main", "devices_offline"), "OFF")
        self.assertIn("device_online", [e["event_type"] for e in self.t.events()])
        self.assertNotIn("problem_recovered", [e["event_type"] for e in self.t.events()])

    def test_source_failure_does_not_forge_device_recovery(self):
        self.s.receive("z2m/plug/availability", b'{"state":"offline"}', retain=True)
        self.assertEqual(self.status("main", "devices_offline"), "ON")
        self.s.receive("z2m/bridge/state", b"offline")
        self.assertEqual(self.status("main", "bridge_offline"), "ON")
        self.assertEqual(self.validity("main", "devices_offline"), "offline")
        self.assertEqual(self.aggregate()["active"][0]["problem_id"],
                         "main:bridge_offline")
        self.assertNotIn("main:devices_offline",
                         [p["problem_id"] for p in self.aggregate()["active"]])

    def test_settings_persist_and_are_isolated(self):
        prefix = f"{ROOT}/command/settings/main/"
        self.assertEqual(self.s.receive(prefix+"rpm_auto", b"OFF"),
                         "problem_setting_updated")
        self.assertEqual(self.s.receive(prefix+"rpm_threshold", b"25"),
                         "problem_setting_updated")
        self.assertEqual(self.store.network_problem_settings("main"), (False, 25))
        self.assertEqual(self.store.network_problem_settings("second"), (True, 10))
        for topic, payload in (("rpm_threshold", b"99999"), ("rpm_auto", b"NO"),
                               ("rpm_threshold", b"3.4")):
            self.assertEqual(self.s.receive(prefix+topic, payload),
                             "problem_setting_ignored")
        self.assertEqual(self.s.receive(prefix+"rpm_auto", b"ON", retain=True),
                         "problem_setting_ignored")
        self.assertEqual(self.store.network_problem_settings("main"), (False, 25))
        self.assertEqual(self.t.last(f"{ROOT}/settings/main/rpm_threshold/state"), "25")

    def test_traffic_low_is_confirmed_per_network_and_recovers(self):
        self.store.update_network_problem_settings("main", auto=False, threshold=10)
        # Prepopulate complete minute buckets: a healthy MQTT rate of 20 RPM.
        start = int(self.clock[0]) - int(self.clock[0]) % 60
        counts = {
            (minute, "main", IEEE1): 20
            for minute in range(start-300, start, 60)
        }
        self.store.commit_counts(counts)
        self.s._traffic_started["main"] = self.clock[0] - 1000
        self.s.tick()
        self.assertEqual(self.status("main", "mqtt_traffic_low"), "OFF")
        for i in range(1, 12):
            self.clock[0] = 10000.0 + 60 * i
            self.s.tick()
        self.assertEqual(self.status("main", "mqtt_traffic_low"), "ON")
        self.assertEqual(self.validity("second", "mqtt_traffic_low"), "offline")
        self.assertIn("problem_started", [e["event_type"] for e in self.t.events()])
        # Recovery requires sustained high RPM, not a single packet burst.
        bucket = int(self.clock[0]) - int(self.clock[0]) % 60
        self.store.commit_counts({
            (minute, "main", IEEE1): 30
            for minute in range(bucket, bucket+10*60, 60)
        })
        for i in range(1, 12):
            self.clock[0] += 60
            self.s.tick()
        self.assertEqual(self.status("main", "mqtt_traffic_low"), "OFF")
        self.assertIn("problem_recovered", [e["event_type"] for e in self.t.events()])

    def test_no_bootstrap_problem_event_or_fake_clean_zero(self):
        self.s.disconnected()
        self.t = Transport()
        self.s.publish = self.t.publish
        self.s.connected()
        self.assertEqual(self.t.last(f"{ROOT}/problems/valid"), "offline")
        self.s.receive("z2m/bridge/state", b"offline", retain=True)
        self.assertEqual(self.status("main", "bridge_offline"), "ON")
        self.assertEqual(self.aggregate()["active"][0]["problem_id"],
                         "main:bridge_offline")
        self.assertEqual(self.t.events(), [])

    def test_model_requires_known_evidence_for_green(self):
        problems = network_problems(
            network_id="main", name="Main", bridge_state="unknown",
            inventory_observed=False, devices=0, offline=0, unknown=0,
            rpm_problem=None, rpm=None, threshold=None,
        )
        self.assertEqual([p.active for p in problems], [None, None, None])

    def test_traffic_hysteresis_keeps_confirmed_fault_through_brief_burst(self):
        detector = TrafficDetector(confirm_seconds=180, recover_seconds=120)
        self.assertIsNone(detector.observe(now=0, rpm=1, threshold=10))
        self.assertTrue(detector.observe(now=180, rpm=1, threshold=10))
        self.assertTrue(detector.observe(now=200, rpm=10, threshold=10))
        self.assertTrue(detector.observe(now=240, rpm=5, threshold=10))
        self.assertTrue(detector.observe(now=250, rpm=14, threshold=10))
        self.assertFalse(detector.observe(now=370, rpm=14, threshold=10))


if __name__ == "__main__":
    unittest.main()
