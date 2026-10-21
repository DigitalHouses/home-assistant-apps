"""Release 0.1.20 FSM, baseline, gap and MQTT ordering acceptance tests."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.fsm import NetworkFSM, aggregate_fsm, auto_threshold
from zigbee_monitor.discovery import EVENT_TOPIC, ROOT
from zigbee_monitor.service import MonitorService


class FSMContractTests(unittest.TestCase):
    def test_auto_threshold_exact_integer_contract_including_zero(self):
        self.assertIsNone(auto_threshold(None))
        self.assertEqual([auto_threshold(x) for x in (0, 0.5, 2, 3.9, 4, 5, 35)],
                         [0, 0, 1, 1, 2, 2, 17])

    def test_auto_floor_zero_does_not_escalate_or_hide_independent_failures(self):
        self.assertEqual(auto_threshold(0.067), 0)
        self.assertEqual(auto_threshold(1.99), 0)
        self.assertEqual(auto_threshold(2.0), 1)
        fsm = NetworkFSM()
        normal = {"bridge_state": "online", "inventory_observed": True,
                  "rpm": 0, "repeaters": {}}
        self.assertEqual(fsm.observe(now=0, threshold=None, **normal)[0], "HEALTHY")
        self.assertEqual(fsm.observe(now=10, threshold=1, **normal)[0], "DEGRADED")
        self.assertIsNotNone(fsm.low_since)
        self.assertEqual(fsm.observe(now=350, threshold=0, **normal)[0], "HEALTHY")
        self.assertIsNone(fsm.low_since)
        self.assertEqual(fsm.observe(now=720, threshold=0, **normal)[0], "HEALTHY")
        self.assertEqual(fsm.observe(
            now=721, bridge_state="offline", inventory_observed=False,
            rpm=None, threshold=0)[0], "CRITICAL")

    def test_no_unknown_and_global_worst_severity(self):
        self.assertEqual(aggregate_fsm([]), "BOOTING")
        self.assertEqual(aggregate_fsm(["HEALTHY", "DEGRADED"]), "DEGRADED")
        self.assertEqual(aggregate_fsm(["CRITICAL", "BOOTING"]), "CRITICAL")
        with self.assertRaises(ValueError):
            aggregate_fsm(["UNKNOWN"])

    def test_initial_sync_then_low_traffic_escalation_and_immediate_recovery(self):
        fsm = NetworkFSM()
        self.assertEqual(fsm.observe(
            now=10, bridge_state="unknown", inventory_observed=False,
            rpm=None, threshold=10)[0], "BOOTING")
        self.assertEqual(fsm.observe(
            now=20, bridge_state="online", inventory_observed=True,
            rpm=20, threshold=10)[0], "HEALTHY")
        self.assertEqual(fsm.boot_completed_at, 20)
        self.assertEqual(fsm.observe(
            now=30, bridge_state="online", inventory_observed=True,
            rpm=5, threshold=10)[0], "DEGRADED")
        self.assertEqual(fsm.observe(
            now=329, bridge_state="online", inventory_observed=True,
            rpm=5, threshold=10)[0], "DEGRADED")
        self.assertEqual(fsm.observe(
            now=330, bridge_state="online", inventory_observed=True,
            rpm=5, threshold=10)[0], "CRITICAL")
        self.assertEqual(fsm.observe(
            now=331, bridge_state="online", inventory_observed=True,
            rpm=11, threshold=10)[0], "HEALTHY")

    def test_zero_threshold_keeps_quiet_network_healthy_for_days(self):
        fsm = NetworkFSM()
        common = {"bridge_state": "online", "inventory_observed": True,
                  "rpm": 0}
        self.assertEqual(fsm.observe(
            now=100, threshold=10, **common), ("DEGRADED", "rpm_below_threshold"))
        self.assertEqual(fsm.observe(
            now=400, threshold=10, **common), ("CRITICAL", "rpm_low_5m"))
        self.assertEqual(fsm.low_since, 100)
        # AUTO learned a real zero: recover immediately and do not retain the
        # previous five-minute RPM incident timer.
        self.assertEqual(fsm.observe(
            now=401, threshold=0, **common), ("HEALTHY", "ok"))
        self.assertIsNone(fsm.low_since)
        for epoch in (900, 3601, 86400, 7 * 86400):
            self.assertEqual(fsm.observe(
                now=epoch, threshold=0, **common), ("HEALTHY", "ok"))
            self.assertIsNone(fsm.low_since)
        # If user re-enables a positive threshold, a fresh five-minute timer
        # must start; the old CRITICAL must not return immediately.
        self.assertEqual(fsm.observe(
            now=7 * 86400 + 1, threshold=10, **common),
            ("DEGRADED", "rpm_below_threshold"))
        self.assertEqual(fsm.observe(
            now=7 * 86400 + 300, threshold=10, **common),
            ("DEGRADED", "rpm_below_threshold"))
        self.assertEqual(fsm.observe(
            now=7 * 86400 + 301, threshold=10, **common),
            ("CRITICAL", "rpm_low_5m"))
        # MANUAL zero must also recover immediately.
        self.assertEqual(fsm.observe(
            now=7 * 86400 + 302, threshold=0, **common),
            ("HEALTHY", "ok"))

    def test_true_zero_and_repeater_confirmation_and_observer_loss(self):
        fsm = NetworkFSM()
        common = {"bridge_state":"online","inventory_observed":True,
                  "rpm":0, "threshold":0}
        self.assertEqual(fsm.observe(now=0, **common)[0], "HEALTHY")
        self.assertEqual(fsm.observe(
            now=10, repeaters={"0x01":"offline"},**common)[0], "HEALTHY")
        self.assertEqual(fsm.observe(
            now=69, repeaters={"0x01":"offline"},**common)[0], "HEALTHY")
        self.assertEqual(fsm.observe(
            now=70, repeaters={"0x01":"offline"},**common)[0], "DEGRADED")
        self.assertEqual(fsm.observe(
            now=71, repeaters={"0x01":"online"},**common)[0], "HEALTHY")
        missing = {"bridge_state":"unknown","inventory_observed":False,
                   "rpm":None,"threshold":0}
        self.assertEqual(fsm.observe(now=80,**missing)[0], "DEGRADED")
        self.assertEqual(fsm.observe(now=380,**missing)[0], "CRITICAL")
        self.assertEqual(fsm.observe(now=381,**common)[0], "HEALTHY")
        self.assertEqual(fsm.observe(
            now=382, bridge_state="offline",inventory_observed=False,
            rpm=None,threshold=0)[0], "CRITICAL")


class ZeroThresholdServiceTests(unittest.TestCase):
    def test_auto_zero_no_rpm_alarm_or_healer_for_two_battery_devices(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = [600.0]
            sent = []
            net = "battery_only"
            store = ActivityStore(Path(temp) / "activity.sqlite")
            self.addCleanup(store.close)
            service = MonitorService(
                ZigbeeMonitor(parse_networks([{
                    "network_id": net, "base_topic": "z2m_battery",
                    "name": "Battery-only network",
                }])), store,
                publish=lambda topic, payload, retain: (
                    sent.append((topic, payload, retain)) or True),
                subscribe=lambda _: True, version="0.1.23",
                now=lambda: clock[0],
            )
            service.connected()
            service.receive("z2m_battery/bridge/devices", json.dumps([
                {"ieee_address":"0x00158d0000000001", "type":"EndDevice",
                 "friendly_name":"Battery_A"},
                {"ieee_address":"0x00158d0000000002", "type":"EndDevice",
                 "friendly_name":"Battery_B"},
            ]).encode(), retain=True)
            service.receive("z2m_battery/bridge/state", b"online", retain=True)
            clock[0] = 631.0  # BOOTING finished + 30 seconds
            service.tick()
            # Without any fresh device message, AUTO is still unknown.
            self.assertIsNone(store.rpm_baseline(net))
            self.assertIsNone(service._traffic_metrics[net]["threshold"])
            self.assertEqual(service._network_fsm[net].state, "HEALTHY")
            clock[0] = 700.0
            service.receive("z2m_battery/Battery_A", b'{"temperature":21.0}')
            service.tick()
            # One message over 100 seconds: baseline 0.60, floor(0.3) = 0.
            self.assertAlmostEqual(store.rpm_baseline(net), 0.60, places=2)
            self.assertEqual(service._traffic_metrics[net]["threshold"], 0)
            # Bridge and inventory continue to be observed; device MQTT
            # activity may be zero for days, but that is not an alarm.
            for epoch in (961, 3601, 7201, 86401, 7 * 86400 + 631):
                clock[0] = float(epoch)
                service.tick()
                self.assertEqual(service._network_fsm[net].state, "HEALTHY")
                self.assertEqual(service._traffic_metrics[net]["traffic_problem"], False)
                self.assertEqual(service._traffic_metrics[net]["threshold"], 0)
            self.assertFalse(any(
                topic == EVENT_TOPIC and
                json.loads(payload).get("current_state") in ("DEGRADED", "CRITICAL")
                for topic, payload, _ in sent
            ))

class StoreContractTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "activity.sqlite"

    def test_baseline_uses_only_complete_healthy_hours(self):
        with ActivityStore(self.path) as store:
            for minute in range(60):
                store.record_rpm_minute(
                    "network",minute_start=minute*60,rpm=10,healthy=True)
            self.assertEqual(store.healthy_hour_baseline(
                "network",until_epoch=3600),10)
            for minute in range(60):
                store.record_rpm_minute(
                    "network",minute_start=3600+minute*60,rpm=2,
                    healthy=minute != 30)
            self.assertEqual(store.healthy_hour_baseline(
                "network",until_epoch=7200),10)
            store.record_rpm_minute(
                "network",minute_start=3600+30*60,rpm=2,healthy=True)
            self.assertEqual(store.healthy_hour_baseline(
                "network",until_epoch=7200),2)
            store.save_rpm_baseline("network",2,epoch=7200)
        with ActivityStore(self.path) as store:
            self.assertEqual(store.rpm_baseline("network"),2)

    def test_weekly_includes_168_hours_seven_days_and_explicit_gaps(self):
        with ActivityStore(self.path) as store:
            store.record_rpm_minute(
                "network",minute_start=3600,rpm=0,healthy=True)
            week = store.weekly_rpm_summary("network",until_epoch=7200)
            self.assertEqual(len(week["hours"]),168)
            self.assertEqual(len(week["days"]),7)
            self.assertEqual(week["coverage_minutes"],1)
            self.assertEqual(week["expected_minutes"],10080)
            self.assertTrue(any(x["avg"] == 0 and x["c"] == 1
                                for x in week["hours"]))
            self.assertTrue(any(x["avg"] is None and x["c"] == 0
                                for x in week["hours"]))

    def test_existing_v019_manual_policy_survives_zero_range_migration(self):
        db = sqlite3.connect(str(self.path))
        db.execute(
            "CREATE TABLE network_problem_settings("
            "network_id TEXT PRIMARY KEY NOT NULL,"
            "auto_rpm_threshold INTEGER NOT NULL DEFAULT 1 "
            "CHECK(auto_rpm_threshold IN (0,1)),"
            "manual_rpm_threshold INTEGER NOT NULL DEFAULT 10 "
            "CHECK(manual_rpm_threshold BETWEEN 1 AND 10000))"
        )
        db.execute("INSERT INTO network_problem_settings VALUES ('network',0,23)")
        db.commit()
        db.close()
        with ActivityStore(self.path) as store:
            self.assertEqual(store.network_problem_settings("network"),(False,23))
            store.update_network_problem_settings("network",threshold=0)
            self.assertEqual(store.network_problem_settings("network"),(False,0))


class ServiceFSMTests(unittest.TestCase):
    def test_auto_waits_for_first_fresh_message_and_uses_elapsed_frequency(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = [600.0]
            store = ActivityStore(Path(temp) / "activity.sqlite")
            self.addCleanup(store.close)
            svc = MonitorService(
                ZigbeeMonitor(parse_networks([{
                    "network_id":"site","base_topic":"z2m","name":"Test",
                }])), store, publish=lambda topic,payload,retain: True,
                subscribe=lambda _: True, version="0.1.22",
                now=lambda: clock[0],
            )
            svc.connected()
            svc.receive("z2m/bridge/devices", json.dumps([{
                "ieee_address":"0x00158d0000000001", "type":"Router",
                "friendly_name":"Device",
            }]).encode(), retain=True)
            svc.receive("z2m/bridge/state", b"online", retain=True)
            clock[0] = 631
            svc.tick()
            self.assertIsNone(store.rpm_baseline("site"))
            self.assertIsNone(svc._traffic_metrics["site"]["threshold"])
            self.assertEqual(svc._traffic_metrics["site"]["rpm"], 0.0)
            self.assertEqual(svc._network_fsm["site"].state, "HEALTHY")
            # A first message after 16 minutes must yield ~0.06 MPM, not 0.2.
            clock[0] = 1600
            svc.receive("z2m/Device", b'{"temperature":20}')
            svc.tick()
            baseline = store.rpm_baseline("site")
            self.assertIsNotNone(baseline)
            self.assertAlmostEqual(baseline, 0.06, places=2)
            self.assertEqual(svc._traffic_metrics["site"]["threshold"], 0)
            clock[0] = 2000
            svc.tick()
            self.assertEqual(svc._network_fsm["site"].state, "HEALTHY")
            self.assertFalse(svc._traffic_metrics["site"]["traffic_problem"])
            self.assertIsNone(svc._network_fsm["site"].low_since)

    def test_retained_fsm_before_events_and_no_initial_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = [600.0]
            sent = []
            store = ActivityStore(Path(temp) / "activity.sqlite")
            self.addCleanup(store.close)
            net = "site"
            svc = MonitorService(
                ZigbeeMonitor(parse_networks([{
                    "network_id":net,"base_topic":"zigbee2mqtt","name":"Test",
                }])),
                store,publish=lambda topic,payload,retain: (
                    sent.append((topic,payload,retain)) or True),
                subscribe=lambda _:True,version="0.1.20",
                now=lambda:clock[0],
            )
            svc.connected()
            svc.receive("zigbee2mqtt/bridge/devices",json.dumps([{
                "ieee_address":"0x00158d0000000001","type":"Router",
                "friendly_name":"Test",
            }]).encode(),retain=True)
            svc.receive("zigbee2mqtt/bridge/state",b"online",retain=True)
            self.assertFalse([v for t,v,_ in sent if t == EVENT_TOPIC])
            clock[0] = 631
            svc.tick()
            self.assertIsNone(store.rpm_baseline(net))
            self.assertIsNone(svc._traffic_metrics[net]["threshold"])
            self.assertEqual(svc._network_fsm[net].state,"HEALTHY")
            store.update_network_problem_settings(net,auto=False,threshold=10)
            svc._update_traffic(632,allow_event=True)
            self.assertEqual(svc._network_fsm[net].state,"DEGRADED")
            events = [(i,json.loads(v)) for i,(t,v,retained) in enumerate(sent)
                      if t == EVENT_TOPIC and
                      json.loads(v)["event_type"] == "network_fsm_changed"]
            self.assertTrue(events)
            self.assertEqual(events[-1][1]["current_state"],"DEGRADED")
            state_index = max(i for i,(t,v,_) in enumerate(sent)
                              if t == f"{ROOT}/networks/{net}/fsm/state"
                              and v == "DEGRADED")
            self.assertLess(state_index,events[-1][0])
            self.assertFalse(sent[events[-1][0]][2])


    def test_reconnect_does_not_publish_stale_healthy_or_transient_events(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = [900.0]
            sent = []
            store = ActivityStore(Path(temp) / "activity.sqlite")
            self.addCleanup(store.close)
            service = MonitorService(
                ZigbeeMonitor(parse_networks([{
                    "network_id":"site","base_topic":"z2m","name":"Test",
                }])),
                store,publish=lambda topic,payload,retain: (
                    sent.append((topic,payload,retain)) or True),
                subscribe=lambda _:True,version="0.1.20",now=lambda:clock[0],
            )
            service.connected()
            inventory = json.dumps([{
                "ieee_address":"0x00158d0000000001",
                "type":"Router","friendly_name":"Device",
            }]).encode()
            service.receive("z2m/bridge/devices", inventory, retain=True)
            service.receive("z2m/bridge/state", b"online", retain=True)
            self.assertEqual(service._network_fsm["site"].state, "HEALTHY")
            service.disconnected()
            sent.clear()
            service.connected()
            replayed_states = [
                value for topic,value,_ in sent
                if topic == f"{ROOT}/networks/site/fsm/state"
            ]
            self.assertEqual(replayed_states, ["DEGRADED"])
            self.assertFalse([value for topic,value,_ in sent
                              if topic == EVENT_TOPIC])
            service.receive("z2m/bridge/devices", inventory, retain=True)
            service.receive("z2m/bridge/state", b"online", retain=True)
            self.assertEqual(service._network_fsm["site"].state, "HEALTHY")
            self.assertFalse([value for topic,value,_ in sent
                              if topic == EVENT_TOPIC])


    def test_minute_history_uses_last_sample_before_boundary_not_next_minute(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = [600.0]
            store = ActivityStore(Path(temp) / "activity.sqlite")
            self.addCleanup(store.close)
            service = MonitorService(
                ZigbeeMonitor(parse_networks([{
                    "network_id":"site","base_topic":"z2m","name":"Test",
                }])),store,
                publish=lambda topic,payload,retain: True,
                subscribe=lambda topic: True,
                version="0.1.20",now=lambda:clock[0],
            )
            service.connected()
            service.receive("z2m/bridge/devices",json.dumps([{
                "ieee_address":"0x00158d0000000001",
                "type":"Router","friendly_name":"Device",
            }]).encode(),retain=True)
            service.receive("z2m/bridge/state",b"online",retain=True)
            service.tick()
            clock[0] = 630
            for _ in range(40):
                service.receive("z2m/Device",b'{"temperature":20}')
            service.tick()
            clock[0] = 659
            service.tick()
            before = service._traffic_metrics["site"]["rpm"]
            clock[0] = 660
            service.tick()
            after = service._traffic_metrics["site"]["rpm"]
            stored = store.conn.execute(
                "SELECT rpm,valid,healthy FROM network_rpm_minutes "
                "WHERE network_id='site' AND minute_start=600"
            ).fetchone()
            self.assertIsNotNone(stored)
            self.assertEqual(stored[0],before)
            self.assertNotEqual(stored[0],after)
            self.assertEqual(stored[1],1)
            # Initial synchronization occurred inside this minute: never
            # mark an only-partially-healthy minute as a healthy-hour sample.
            self.assertEqual(stored[2],0)
            # A subsequent fully observed minute is eligible for baseline.
            clock[0] = 690
            for _ in range(40):
                service.receive("z2m/Device",b'{"temperature":20}')
            service.tick()
            clock[0] = 719
            service.tick()
            clock[0] = 720
            service.tick()
            second = store.conn.execute(
                "SELECT rpm,valid,healthy FROM network_rpm_minutes "
                "WHERE network_id='site' AND minute_start=660"
            ).fetchone()
            self.assertIsNotNone(second)
            self.assertEqual(second[1:],(1,1))


if __name__ == "__main__":
    unittest.main()
