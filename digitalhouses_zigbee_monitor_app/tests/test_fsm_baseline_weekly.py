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
                         [0, 1, 1, 2, 2, 3, 18])

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
            self.assertEqual(store.rpm_baseline(net),0)
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


if __name__ == "__main__":
    unittest.main()
