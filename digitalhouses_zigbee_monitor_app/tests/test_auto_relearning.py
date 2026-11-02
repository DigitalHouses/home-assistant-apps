"""Trend-driven automatic MPM relearning and safety regression tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.fsm import NetworkFSM
from zigbee_monitor.service import MonitorService

NETWORK = "z2m_auto_relearn"
BASE = "zigbee2mqtt"
A = "0x00158d0000000001"
B = "0x00158d0000000002"


def seed_low_regime(
    store: ActivityStore, *, end: int, minutes: int = 30,
    messages_every: int = 5, complete: bool = True,
    activity: bool = True, declining: bool = False,
) -> None:
    """A lower reporting rate: genuine minute observations and MQTT evidence."""
    start = end - minutes * 60
    assert start >= 0 and start % 60 == 0
    for i in range(minutes):
        if not complete and i == 5:
            continue
        store.record_rpm_minute(
            NETWORK, minute_start=start + i * 60, rpm=0.2, healthy=False)
    if activity:
        times = list(range(0, minutes, messages_every))
        if declining:
            times = [i for i in times if i < minutes//2]
            times += [minutes - 1]
        store.commit_counts({
            (start + i * 60, NETWORK, A): 1 for i in times
        })


class StoreTrendTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "state.sqlite"
        self.store = ActivityStore(self.path)
        self.addCleanup(self.store.close)
        self.end = 1000 * 60

    def candidate(self, threshold=30):
        return self.store.stable_low_traffic_baseline(
            NETWORK, until_epoch=self.end, threshold=threshold, old_baseline=60)

    def test_high_traffic_relearns_after_15_minutes(self):
        seed_low_regime(
            self.store, end=self.end, minutes=15, messages_every=2)
        self.assertEqual(self.candidate(), (round(8/15, 4), 15))

    def test_low_traffic_relearns_after_30_minutes_without_device_analysis(self):
        seed_low_regime(self.store, end=self.end)
        self.assertEqual(self.candidate(), (0.2, 30))
        self.assertEqual(self.store.recent_device_message_count(
            NETWORK, until_epoch=self.end), 6)

    def test_sparse_traffic_can_relearn_after_60_minutes(self):
        seed_low_regime(
            self.store, end=self.end, minutes=60, messages_every=10)
        self.assertEqual(self.candidate(), (0.1, 60))

    def test_complete_silence_cannot_be_new_normal(self):
        seed_low_regime(self.store, end=self.end, activity=False)
        self.assertIsNone(self.candidate())

    def test_missing_observed_minute_rejects_relearning(self):
        seed_low_regime(self.store, end=self.end, complete=False)
        self.assertIsNone(self.candidate())

    def test_ongoing_collapse_is_not_stable(self):
        seed_low_regime(self.store, end=self.end, declining=True)
        self.assertIsNone(self.candidate())

    def test_stale_old_baseline_is_bypassed_after_relearning(self):
        seed_low_regime(self.store, end=self.end)
        for minute in range(60):
            self.store.record_rpm_minute(
                NETWORK, minute_start=self.end-7*3600+minute*60,
                rpm=60, healthy=True)
        self.assertEqual(self.store.healthy_rolling_baseline(
            NETWORK, until_epoch=self.end), 60)
        self.store.adopt_stable_low_baseline(NETWORK, 0.2, epoch=self.end)
        self.assertEqual(self.store.rpm_baseline(NETWORK), 0.2)
        self.assertEqual(self.store.rpm_relearned_since(NETWORK), self.end)
        self.assertIsNone(self.store.healthy_rolling_baseline(
            NETWORK, until_epoch=self.end))
        self.store.close()
        with ActivityStore(self.path) as reopened:
            self.assertEqual(reopened.rpm_relearned_since(NETWORK), self.end)
            for minute in range(60):
                reopened.record_rpm_minute(
                    NETWORK, minute_start=self.end+minute*60,
                    rpm=0.2, healthy=True)
            self.assertEqual(reopened.healthy_rolling_baseline(
                NETWORK, until_epoch=self.end+3600), 0.2)


class RelearnFSMTests(unittest.TestCase):
    def test_grace_stays_degraded_up_to_hour_not_critical(self):
        fsm = NetworkFSM()
        params = dict(bridge_state="online", inventory_observed=True,
                      rpm=0.2, threshold=30, repeaters={})
        self.assertEqual(fsm.observe(now=0, relearn_pending=True, **params),
                         ("DEGRADED", "rpm_relearn_observing"))
        self.assertEqual(fsm.observe(now=350, relearn_pending=True, **params),
                         ("DEGRADED", "rpm_relearn_observing"))
        self.assertEqual(fsm.observe(now=3599, relearn_pending=True, **params),
                         ("DEGRADED", "rpm_relearn_observing"))
        self.assertEqual(fsm.observe(now=3601, relearn_pending=True, **params),
                         ("CRITICAL", "rpm_low_5m"))
        self.assertEqual(fsm.observe(
            now=3602, relearn_pending=False, **params),
            ("CRITICAL", "rpm_low_5m"))

    def test_bridge_offline_is_critical_even_during_relearn(self):
        fsm = NetworkFSM()
        params = dict(bridge_state="online", inventory_observed=True,
                      rpm=0.2, threshold=30, repeaters={})
        fsm.observe(now=0, relearn_pending=True, **params)
        self.assertEqual(fsm.observe(
            now=100, bridge_state="offline", inventory_observed=False,
            rpm=None, threshold=30, relearn_pending=True),
            ("CRITICAL", "bridge_offline"))
        self.assertEqual(fsm.observe(
            now=101, relearn_pending=True,
            bridge_state="online", inventory_observed=True,
            rpm=0.2, threshold=30, repeaters={"0x01": "offline"})[0], "DEGRADED")
        self.assertEqual(fsm.observe(
            now=163, relearn_pending=True,
            bridge_state="online", inventory_observed=True,
            rpm=0.2, threshold=30, repeaters={"0x01": "offline"}),
            ("DEGRADED", "repeater_offline"))


class ServiceAutoRelearnTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = [1000*60.]
        self.store = ActivityStore(Path(tmp.name) / "state.sqlite")
        self.addCleanup(self.store.close)
        self.sent = []
        self.service = MonitorService(
            ZigbeeMonitor(parse_networks([{
                "network_id": NETWORK, "base_topic": BASE, "name": "zigbee2mqtt",
            }])), self.store,
            publish=lambda topic, payload, retained: (
                self.sent.append((topic, payload, retained)) or True),
            subscribe=lambda _: True,
            version="0.1.26", now=lambda: self.clock[0],
        )
        self.service.connected()
        self.service.receive(BASE + "/bridge/devices", json.dumps([
            {"ieee_address": A, "type": "Router", "friendly_name": "A"},
            {"ieee_address": B, "type": "Router", "friendly_name": "B"},
        ]).encode(), retain=True)
        self.service.receive(BASE + "/bridge/state", b"online", retain=True)
        self.service.receive(BASE + "/A/availability", b'{"state":"online"}', retain=True)
        self.service.receive(BASE + "/B/availability", b'{"state":"online"}', retain=True)
        self.store.save_rpm_baseline(NETWORK, 60, epoch=int(self.clock[0])-3600)
        seed_low_regime(self.store, end=int(self.clock[0]))
        self.service.receive(BASE + "/A", b'{"temperature":20}', retain=False)
        self.service._rpm_sample_minute = int(self.clock[0]) // 60 - 1
        self.service._rpm_completed[NETWORK] = (
            self.service._rpm_sample_minute, 0.2, False)

    def test_auto_recovers_after_30_minute_stable_low_trend(self):
        self.service._update_traffic(int(self.clock[0]))
        self.assertEqual(
            self.service._network_fsm[NETWORK].reason, "rpm_relearn_observing")
        self.service._network_fsm[NETWORK].low_since = self.clock[0] - 500
        self.service._update_traffic(int(self.clock[0]))
        self.assertEqual(self.service._network_fsm[NETWORK].state, "DEGRADED")
        self.service._record_rpm_samples(int(self.clock[0]))
        self.assertEqual(self.store.rpm_baseline(NETWORK), 0.2)
        self.service._update_traffic(int(self.clock[0]) + 10)
        self.assertEqual(self.service._network_fsm[NETWORK].state, "HEALTHY")
        self.assertEqual(self.service._traffic_metrics[NETWORK]["threshold"], 0.1)
        self.assertEqual(self.store.rpm_relearned_since(NETWORK),
                         int(self.clock[0]))
        self.assertEqual(self.store.network_problem_settings(NETWORK), (True, 10))

    def test_peer_offline_blocks_relearn_and_grace(self):
        self.service.receive(BASE + "/B/availability", b'{"state":"offline"}')
        self.service._update_traffic(int(self.clock[0]))
        self.assertNotEqual(
            self.service._network_fsm[NETWORK].reason, "rpm_relearn_observing")
        self.service._record_rpm_samples(int(self.clock[0]))
        self.assertEqual(self.store.rpm_baseline(NETWORK), 60)

    def test_manual_mode_is_never_relearned(self):
        self.store.update_network_problem_settings(
            NETWORK, auto=False, threshold=30)
        self.service._update_traffic(int(self.clock[0]))
        self.service._record_rpm_samples(int(self.clock[0]))
        self.assertEqual(self.store.rpm_baseline(NETWORK), 60)
        self.assertEqual(self.store.network_problem_settings(NETWORK), (False, 30))

    def test_no_recent_messages_does_not_hide_fault(self):
        self.store.conn.execute(
            "DELETE FROM message_minutes WHERE network_id=?", (NETWORK,))
        self.store.conn.commit()
        self.service._update_traffic(int(self.clock[0]))
        self.assertNotEqual(
            self.service._network_fsm[NETWORK].reason, "rpm_relearn_observing")
        self.service._record_rpm_samples(int(self.clock[0]))
        self.assertEqual(self.store.rpm_baseline(NETWORK), 60)


if __name__ == "__main__":
    unittest.main()
