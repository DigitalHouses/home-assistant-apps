"""RPM must be visible immediately, without suppressing incident warm-up."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.discovery import ROOT, state_topic, validity_topic
from zigbee_monitor.service import MonitorService

IEEE = "0x00158d0000000001"
NETWORK = "floor_1"
BASE = "zigbee2mqtt_1"


class LiveRPMTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = [600.0]
        self.published = []
        self.store = ActivityStore(Path(tmp.name) / "activity.sqlite")
        self.addCleanup(self.store.close)
        self.service = MonitorService(
            ZigbeeMonitor(parse_networks([{
                "network_id": NETWORK, "base_topic": BASE, "name": BASE,
            }])),
            self.store,
            publish=lambda topic, value, retain: (
                self.published.append((topic, value, retain)) or True
            ),
            subscribe=lambda _topic: True,
            version="0.1.15",
            now=lambda: self.clock[0],
        )
        self.service.connected()

    def msg(self, suffix, value=b"{}", *, retain=False, dup=False):
        return self.service.receive(
            BASE + "/" + suffix, value, retain=retain, dup=dup,
            observed_at=int(self.clock[0]),
        )

    def last(self, topic):
        return next((body for t, body, _ in reversed(self.published)
                     if t == topic), None)

    def row(self):
        return json.loads(self.last(state_topic("networks_details")))["networks"][0]

    def start_online(self):
        self.msg("bridge/devices", json.dumps([{
            "ieee_address": IEEE, "type": "Router", "friendly_name": "Test",
            "definition": {"model": "test", "vendor": "Test"},
        }]).encode(), retain=True)
        self.msg("bridge/state", b"online", retain=True)

    def test_boot_shows_numeric_zero_instead_of_unknown(self):
        self.start_online()
        self.assertEqual(self.row()["rpm"], 0.0)
        self.assertEqual(self.row()["rpm_phase"], "warming_up")
        self.assertIn("mqtt_traffic_low", self.row()["problem_unknown"])
        self.assertNotIn("mqtt_traffic_low", self.row()["problem_active"])
        self.assertEqual(
            self.last(validity_topic("messages_rate_5m")), "offline"
        )

    def test_live_messages_appear_within_ten_seconds_and_are_not_alarm_evidence(self):
        self.start_online()
        for _ in range(3):
            self.msg("Test", b'{"temperature":25}')
        self.clock[0] = 615
        self.service.tick()
        self.assertEqual(self.row()["rpm"], 12.0)
        self.assertEqual(self.row()["rpm_phase"], "warming_up")
        self.assertIsNone(self.row()["traffic_problem"])
        self.assertIn("mqtt_traffic_low", self.row()["problem_unknown"])
        self.assertEqual(
            self.last(validity_topic("messages_rate_5m")), "offline"
        )

    def test_retained_replay_and_duplicate_do_not_inflate_rate(self):
        self.start_online()
        for _ in range(25):
            self.msg("Test", b'{"temperature":25}', retain=True)
        for _ in range(10):
            self.msg("Test", b'{"temperature":25}', dup=True)
        self.clock[0] = 611
        self.service.tick()
        self.assertEqual(self.row()["rpm"], 0.0)
        self.msg("Test", b'{"temperature":25}')
        self.clock[0] = 621
        self.service.tick()
        self.assertGreater(self.row()["rpm"], 0)
        self.assertLess(self.row()["rpm"], 10)

    def test_false_zero_is_not_confirmed_problem_during_boot(self):
        self.start_online()
        self.store.update_network_problem_settings(
            NETWORK, auto=False, threshold=10,
        )
        for minute in range(601, 900, 11):
            self.clock[0] = float(minute)
            self.service.tick()
        self.assertEqual(self.row()["rpm"], 0)
        self.assertEqual(self.row()["rpm_phase"], "warming_up")
        self.assertIsNone(self.row()["traffic_problem"])
        self.assertIn("mqtt_traffic_low", self.row()["problem_unknown"])

    def test_preview_reset_after_disconnect_and_source_restart(self):
        self.start_online()
        self.msg("Test")
        self.clock[0] = 614
        self.service.tick()
        self.assertGreater(self.row()["rpm"], 0)
        self.service.disconnected()
        self.service.connected()
        self.start_online()
        self.assertEqual(self.row()["rpm"], 0.0)
        self.assertEqual(self.row()["rpm_phase"], "warming_up")

    def test_other_network_does_not_inherit_rate(self):
        second = "zigbee2mqtt_office"
        self.store.register_network("0x00158d0000000002", second, observed_at=601)
        new, _ = self.store.register_network("0x00158d0000000002", second, observed_at=601)
        self.service.monitor.add_network(new)
        self.start_online()
        self.service.receive(
            second + "/bridge/state", b"online", retain=True,
            observed_at=600,
        )
        self.msg("Test")
        self.clock[0] = 620
        self.service.tick()
        rows = json.loads(self.last(state_topic("networks_details")))["networks"]
        self.assertEqual(len(rows), 2)
        self.assertGreater(next(r["rpm"] for r in rows if r["network_id"] == NETWORK), 0)
        self.assertEqual(next(r["rpm"] for r in rows if r["network_id"] != NETWORK), 0.0)


if __name__ == "__main__":
    unittest.main()
