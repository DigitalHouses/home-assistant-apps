"""Automatic low-traffic regime adaptation without accepting total Zigbee silence."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.service import MonitorService


NETWORK = "z2m_auto_relearn"
BASE = "zigbee2mqtt"
A = "0x00158d0000000001"
B = "0x00158d0000000002"


def seed_low_regime(
    store: ActivityStore, *, end: int, two_senders: bool = True,
    activity: bool = True, complete: bool = True,
) -> None:
    start = end - 360 * 60
    assert start >= 0 and start % 60 == 0
    for i in range(360):
        if not complete and i == 130:
            continue
        store.record_rpm_minute(
            NETWORK, minute_start=start + i * 60, rpm=0.2, healthy=False
        )
    if activity:
        counts = {
            (start + i*60, NETWORK, A if not two_senders or i % 2 else B): 1
            for i in range(0, 360, 5)
        }
        store.commit_counts(counts)


class StoreLowRegimeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "state.sqlite"
        self.store = ActivityStore(self.path)
        self.addCleanup(self.store.close)
        self.end = 1000 * 60

    def test_six_hours_two_devices_relearn_even_from_unhealthy_minutes(self):
        seed_low_regime(self.store, end=self.end)
        self.assertEqual(self.store.stable_low_traffic_baseline(
            NETWORK, until_epoch=self.end, threshold=30), 0.2)

    def test_silence_is_never_accepted_as_new_normal(self):
        seed_low_regime(self.store, end=self.end, activity=False)
        self.assertIsNone(self.store.stable_low_traffic_baseline(
            NETWORK, until_epoch=self.end, threshold=30))

    def test_single_talker_is_not_proof_of_healthy_network(self):
        seed_low_regime(self.store, end=self.end, two_senders=False)
        self.assertIsNone(self.store.stable_low_traffic_baseline(
            NETWORK, until_epoch=self.end, threshold=30))

    def test_missing_minute_breaks_continuity(self):
        seed_low_regime(self.store, end=self.end, complete=False)
        self.assertIsNone(self.store.stable_low_traffic_baseline(
            NETWORK, until_epoch=self.end, threshold=30))

    def test_instability_rejected_and_recent_message_required(self):
        seed_low_regime(self.store, end=self.end)
        # Make the second half lose all its traffic, despite six hours of
        # numeric RPM snapshots from the coordinator's prior session.
        self.store.conn.execute(
            "DELETE FROM message_minutes WHERE network_id=? AND bucket_start>=?",
            (NETWORK, self.end - 3 * 3600),
        )
        self.store.conn.commit()
        self.assertIsNone(self.store.stable_low_traffic_baseline(
            NETWORK, until_epoch=self.end, threshold=30))

    def test_persist_relearn_boundary_prevents_old_spam_from_returning(self):
        seed_low_regime(self.store, end=self.end)
        for minute in range(60):
            self.store.record_rpm_minute(
                NETWORK, minute_start=self.end - 7 * 3600 + minute*60,
                rpm=60, healthy=True,
            )
        self.assertEqual(self.store.healthy_rolling_baseline(
            NETWORK, until_epoch=self.end), 60)
        self.store.adopt_stable_low_baseline(NETWORK, 0.2, epoch=self.end)
        self.assertEqual(self.store.rpm_baseline(NETWORK), 0.2)
        self.assertEqual(self.store.rpm_relearned_since(NETWORK), self.end)
        self.assertIsNone(self.store.healthy_rolling_baseline(
            NETWORK, until_epoch=self.end))
        self.store.close()
        # Reopening the App must retain the generation boundary.
        with ActivityStore(self.path) as reopened:
            self.assertEqual(reopened.rpm_relearned_since(NETWORK), self.end)
            self.assertEqual(reopened.rpm_baseline(NETWORK), 0.2)
            for minute in range(60):
                reopened.record_rpm_minute(
                    NETWORK, minute_start=self.end + minute*60,
                    rpm=0.2, healthy=True,
                )
            self.assertEqual(reopened.healthy_rolling_baseline(
                NETWORK, until_epoch=self.end+3600), 0.2)


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
                self.sent.append((topic, payload, retained)) or True
            ),
            subscribe=lambda _: True,
            version="0.1.25", now=lambda: self.clock[0],
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
            self.service._rpm_sample_minute, 0.2, False,
        )

    def test_auto_recovers_from_stale_rpm_critical_without_operator(self):
        self.service._update_traffic(int(self.clock[0]))
        self.assertEqual(self.service._network_fsm[NETWORK].state, "DEGRADED")
        # Simulate prior persistent low-traffic escalation.
        self.service._network_fsm[NETWORK].low_since = self.clock[0] - 500
        self.service._update_traffic(int(self.clock[0]))
        self.assertEqual(self.service._network_fsm[NETWORK].state, "CRITICAL")
        self.service._record_rpm_samples(int(self.clock[0]))
        self.assertEqual(self.store.rpm_baseline(NETWORK), 0.2)
        self.service._update_traffic(int(self.clock[0]) + 10)
        self.assertEqual(self.service._network_fsm[NETWORK].state, "HEALTHY")
        self.assertEqual(self.service._traffic_metrics[NETWORK]["threshold"], 0)
        self.assertEqual(self.store.rpm_relearned_since(NETWORK),
                         int(self.clock[0]))
        # The operator's MANUAL settings are unchanged.
        self.assertEqual(self.store.network_problem_settings(NETWORK), (True, 10))

    def test_peer_offline_blocks_automatic_relearning(self):
        self.service.receive(BASE + "/B/availability", b'{"state":"offline"}')
        self.service._update_traffic(int(self.clock[0]))
        self.service._record_rpm_samples(int(self.clock[0]))
        self.assertEqual(self.store.rpm_baseline(NETWORK), 60)

    def test_manual_mode_is_never_overwritten(self):
        self.store.update_network_problem_settings(NETWORK, auto=False, threshold=30)
        self.service._update_traffic(int(self.clock[0]))
        self.service._record_rpm_samples(int(self.clock[0]))
        self.assertEqual(self.store.rpm_baseline(NETWORK), 60)
        self.assertEqual(self.store.network_problem_settings(NETWORK), (False, 30))


if __name__ == "__main__":
    unittest.main()
