"""Fractional AUTO thresholds with gap-safe, adaptive MQTT observation periods."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.discovery import network_rpm_threshold_topic
from zigbee_monitor.fsm import auto_rpm_window_minutes, auto_threshold
from zigbee_monitor.service import MonitorService


NETWORK = "test_network"
BASE = "zigbee2mqtt"
IEEE = "0x00158d0000000001"


def seed_window(store, *, end, minutes, message_every=3, missing=None):
    start = end - minutes * 60
    for i in range(minutes):
        if i == missing:
            continue
        store.record_rpm_minute(
            NETWORK, minute_start=start + i*60, rpm=0,
            healthy=True,
        )
    if message_every:
        store.commit_counts({
            (start+i*60, NETWORK, IEEE): 1
            for i in range(0, minutes, message_every)
        })


class StorageWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ActivityStore(Path(self.temp.name) / "db.sqlite")
        self.addCleanup(self.store.close)
        self.end = 180000

    def test_complete_thirty_minute_mqtt_window_not_5m_snapshot(self):
        seed_window(self.store, end=self.end, minutes=30)
        self.assertEqual(self.store.observed_mpm_window(
            NETWORK, until_epoch=self.end, minutes=30), round(10 / 30, 4))
        self.assertIsNone(self.store.observed_mpm_window(
            NETWORK, until_epoch=self.end, minutes=60))

    def test_complete_sixty_minute_window(self):
        seed_window(self.store, end=self.end, minutes=60, message_every=10)
        self.assertEqual(self.store.observed_mpm_window(
            NETWORK, until_epoch=self.end, minutes=60), 0.1)
        self.assertEqual(auto_rpm_window_minutes(.2), 60)
        self.assertEqual(auto_threshold(.2), .1)

    def test_missing_observation_is_not_a_zero(self):
        seed_window(self.store, end=self.end, minutes=30, missing=17)
        self.assertIsNone(self.store.observed_mpm_window(
            NETWORK, until_epoch=self.end, minutes=30))

    def test_fully_observed_silence_is_an_actual_zero(self):
        seed_window(self.store, end=self.end, minutes=30, message_every=0)
        self.assertEqual(self.store.observed_mpm_window(
            NETWORK, until_epoch=self.end, minutes=30), 0)


class ServiceWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = [180000.]
        self.store = ActivityStore(Path(self.temp.name) / "db.sqlite")
        self.addCleanup(self.store.close)
        self.sent = []
        self.service = MonitorService(
            ZigbeeMonitor(parse_networks([{
                "network_id": NETWORK, "base_topic": BASE,
                "name": "quiet network",
            }])), self.store,
            publish=lambda topic, value, retained: (
                self.sent.append((topic, value, retained)) or True),
            subscribe=lambda _: True, now=lambda: self.clock[0],
            version="0.1.27",
        )
        self.service.connected()
        self.service.receive(BASE + "/bridge/devices", json.dumps([{
            "ieee_address": IEEE, "type": "EndDevice",
            "friendly_name": "sensor",
        }]).encode(), retain=True)
        self.service.receive(BASE + "/bridge/state", b"online", retain=True)
        self.service.receive(BASE + "/sensor/availability",
                             b'{"state":"online"}', retain=True)

    def last(self, topic):
        return next((value for t, value, _ in reversed(self.sent)
                     if t == topic), None)

    def test_quiet_thirty_minute_network_healthy_despite_5m_zero(self):
        self.store.save_rpm_baseline(NETWORK, 0.5389, epoch=179000)
        seed_window(self.store, end=int(self.clock[0]), minutes=30)
        self.service._live_rpm = lambda nid, epoch: 0.0
        self.service._live_started[NETWORK] = self.clock[0] - 2000
        self.service._update_traffic(int(self.clock[0]))
        m = self.service._traffic_metrics[NETWORK]
        self.assertEqual(m["rpm"], 0)
        self.assertEqual(m["rpm_alarm"], round(10/30, 4))
        self.assertEqual(m["rpm_alarm_window_minutes"], 30)
        self.assertEqual(m["threshold"], .27)
        self.assertFalse(m["traffic_problem"])
        self.assertEqual(self.service._network_fsm[NETWORK].state, "HEALTHY")
        self.service._publish_networks()
        self.assertEqual(self.last(network_rpm_threshold_topic(NETWORK)), "0.27")

    def test_quiet_sixty_minute_window_healthy_despite_5m_zero(self):
        self.store.save_rpm_baseline(NETWORK, .2, epoch=179000)
        seed_window(self.store, end=int(self.clock[0]),
                    minutes=60, message_every=10)
        self.service._live_rpm = lambda nid, epoch: 0.0
        self.service._live_started[NETWORK] = self.clock[0] - 4000
        self.service._update_traffic(int(self.clock[0]))
        m = self.service._traffic_metrics[NETWORK]
        self.assertEqual(m["rpm_alarm"], .1)
        self.assertEqual(m["rpm_alarm_window_minutes"], 60)
        self.assertEqual(m["threshold"], .1)
        self.assertFalse(m["traffic_problem"])
        self.assertEqual(self.service._network_fsm[NETWORK].state, "HEALTHY")

    def test_real_confirmed_silence_triggers_low_traffic(self):
        self.store.save_rpm_baseline(NETWORK, .5389, epoch=179000)
        seed_window(self.store, end=int(self.clock[0]),
                    minutes=30, message_every=0)
        self.service._live_rpm = lambda nid, epoch: 0.0
        self.service._live_started[NETWORK] = self.clock[0] - 2000
        self.service._update_traffic(int(self.clock[0]))
        self.assertTrue(self.service._traffic_metrics[NETWORK]["traffic_problem"])
        self.assertEqual(self.service._network_fsm[NETWORK].state, "DEGRADED")

    def test_reconnect_cannot_reuse_pre_reconnect_history_as_live_alarm(self):
        self.store.save_rpm_baseline(NETWORK, .5389, epoch=179000)
        seed_window(self.store, end=int(self.clock[0]),
                    minutes=30, message_every=0)
        self.service._live_rpm = lambda nid, epoch: 0.0
        self.service._live_started[NETWORK] = self.clock[0] - 120
        self.service._update_traffic(int(self.clock[0]))
        m = self.service._traffic_metrics[NETWORK]
        self.assertIsNone(m["rpm_alarm"])
        self.assertEqual(m["rpm_alarm_phase"], "warming_up")
        self.assertIsNone(m["traffic_problem"])
        self.assertEqual(self.service._network_fsm[NETWORK].state, "HEALTHY")

    def test_manual_threshold_and_five_minute_window_unchanged(self):
        self.store.save_rpm_baseline(NETWORK, .5389, epoch=179000)
        self.store.update_network_problem_settings(NETWORK, auto=False, threshold=10)
        self.service._live_rpm = lambda nid, epoch: 0
        self.service._update_traffic(int(self.clock[0]))
        m = self.service._traffic_metrics[NETWORK]
        self.assertEqual(m["threshold"], 10)
        self.assertEqual(m["rpm_alarm_window_minutes"], 5)
        self.assertEqual(m["rpm_alarm"], 0)
        self.assertEqual(self.service._network_fsm[NETWORK].state, "DEGRADED")
        self.service._publish_networks()
        self.assertEqual(self.last(network_rpm_threshold_topic(NETWORK)), "10")


if __name__ == "__main__":
    unittest.main()
