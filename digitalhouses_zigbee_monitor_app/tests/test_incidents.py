"""Durable, source-authoritative Zigbee incidents; no Recorder JSON/history abuse."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.discovery import EVENT_TOPIC, state_topic, validity_topic
from zigbee_monitor.service import MonitorService

IEEE1 = "0x00158d0000000001"
IEEE2 = "0x00158d0000000002"
BASE = "zigbee2mqtt"
NET = "site_1"


def inventory():
    return json.dumps([
        {"type": "Router", "ieee_address": IEEE1, "friendly_name": "plug"},
        {"type": "EndDevice", "ieee_address": IEEE2, "friendly_name": "battery"},
    ]).encode()


class Transport:
    def __init__(self):
        self.sent = []

    def publish(self, topic, payload, retain):
        self.sent.append((topic, payload, retain))
        return True

    def subscribe(self, topic):
        return True

    def last(self, topic):
        for key, payload, _ in reversed(self.sent):
            if key == topic:
                return payload
        return None

    def events(self):
        return [json.loads(payload) for topic, payload, _ in self.sent
                if topic == EVENT_TOPIC]


class DurableIncidentsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "zigbee.sqlite"
        self.store = ActivityStore(self.path)
        self.addCleanup(lambda: self.store.conn.close())
        self.t = Transport()
        self.clock = [600.0]
        self.create_service()
        self.s.connected()
        self.receive("bridge/devices", inventory(), retain=True)
        self.receive("bridge/state", b'online', retain=True)

    def create_service(self):
        self.s = MonitorService(
            ZigbeeMonitor(parse_networks([{
                "network_id": NET, "base_topic": BASE, "name": "Main"
            }])),
            self.store, publish=self.t.publish, subscribe=self.t.subscribe,
            version="0.1.7", now=lambda: self.clock[0],
        )

    def receive(self, topic, payload, **kw):
        return self.s.receive(BASE + "/" + topic, payload, **kw)

    def details(self):
        return json.loads(self.t.last(state_topic("incidents_details")))

    def test_zero_is_unknown_until_each_device_is_observed(self):
        self.assertEqual(self.t.last(validity_topic("incidents")), "offline")
        self.assertEqual(self.details()["incidents"], [])
        self.assertFalse(self.details()["observation_complete"])
        self.receive("plug/availability", b'{"state":"online"}', retain=True)
        self.assertEqual(self.t.last(validity_topic("incidents")), "offline")
        self.receive("battery/availability", b'{"state":"online"}', retain=True)
        self.assertEqual(self.t.last(state_topic("incidents")), "0")
        self.assertEqual(self.t.last(validity_topic("incidents")), "online")
        self.assertTrue(self.details()["observation_complete"])

    def test_retained_offline_is_visible_without_fabricated_onset_or_event(self):
        self.receive("plug/availability", b'{"state":"offline"}', retain=True)
        d = self.details()
        self.assertEqual(self.t.last(state_topic("incidents")), "1")
        self.assertFalse(d["observation_complete"])
        self.assertEqual(len(d["incidents"]), 1)
        i = d["incidents"][0]
        self.assertEqual(i["kind"], "device_offline")
        self.assertEqual(i["object_id"], IEEE1)
        self.assertEqual(i["name"], "plug")
        self.assertEqual(i["started_at"], None)
        self.assertEqual(i["first_observed_at"], "1970-01-01T00:10:00+00:00")
        self.assertEqual(self.t.events(), [])
        self.receive("plug/availability", b'{"state":"offline"}', retain=True)
        self.assertEqual(self.details()["incidents"][0]["incident_id"], i["incident_id"])
        self.assertEqual(self.store.incident_history()[2], 1)

    def test_live_offline_to_online_closes_incident_with_duration_and_history(self):
        self.receive("plug/availability", b'{"state":"online"}', retain=True)
        self.receive("battery/availability", b'{"state":"online"}', retain=True)
        self.clock[0] = 630.0
        self.receive("plug/availability", b'{"state":"offline"}')
        opened = self.details()["incidents"][0]
        self.assertEqual(opened["started_at"], "1970-01-01T00:10:30+00:00")
        self.assertEqual(self.t.last(state_topic("incidents")), "1")
        self.assertEqual([e["event_type"] for e in self.t.events()], ["device_offline"])
        self.clock[0] = 750.0
        self.receive("plug/availability", b'{"state":"online"}')
        d = self.details()
        self.assertEqual(d["total"], 0)
        self.assertEqual(self.t.last(state_topic("incidents")), "0")
        self.assertEqual(d["recent_resolved"][0]["incident_id"], opened["incident_id"])
        self.assertEqual(d["recent_resolved"][0]["duration_seconds"], 120)
        self.assertEqual(d["recent_resolved"][0]["resolution_source"], "live_transition")
        self.assertEqual([e["event_type"] for e in self.t.events()],
                         ["device_offline", "device_online"])

    def test_z2m_offline_generates_one_source_incident_not_device_flood(self):
        self.receive("plug/availability", b'{"state":"online"}', retain=True)
        self.receive("battery/availability", b'{"state":"online"}', retain=True)
        self.clock[0] = 680
        self.receive("bridge/state", b'offline')
        d = self.details()
        self.assertEqual(self.t.last(state_topic("incidents")), "1")
        self.assertEqual([i["kind"] for i in d["incidents"]], ["zigbee2mqtt_offline"])
        self.assertEqual([e["event_type"] for e in self.t.events()],
                         ["zigbee2mqtt_offline"])
        self.receive("plug/availability", b'{"state":"offline"}')
        self.assertEqual(self.store.incident_history()[2], 1)
        self.assertEqual(len(self.t.events()), 1)
        self.clock[0] = 900
        self.receive("bridge/state", b'online')
        self.assertEqual(self.t.last(validity_topic("incidents")), "offline")
        self.assertEqual(len(self.details()["recent_resolved"]), 1)
        self.assertEqual(self.details()["recent_resolved"][0]["duration_seconds"], 220)

    def test_restart_retains_same_active_incident_and_recovers_no_false_alert(self):
        self.receive("plug/availability", b'{"state":"online"}', retain=True)
        self.clock[0] = 620
        self.receive("plug/availability", b'{"state":"offline"}')
        first_id = self.details()["incidents"][0]["incident_id"]
        self.s.disconnected()
        self.t = Transport()
        self.clock[0] = 800
        self.create_service()
        self.s.connected()
        self.receive("bridge/devices", inventory(), retain=True)
        self.receive("bridge/state", b'online', retain=True)
        self.receive("plug/availability", b'{"state":"offline"}', retain=True)
        self.assertEqual(self.details()["incidents"][0]["incident_id"], first_id)
        self.assertEqual(self.details()["incidents"][0]["started_at"],
                         "1970-01-01T00:10:20+00:00")
        self.assertEqual(self.t.events(), [])
        self.clock[0] = 810
        self.receive("plug/availability", b'{"state":"online"}', retain=True)
        self.assertEqual(self.t.events(), [])
        self.assertEqual(self.store.incident_history()[2], 0)
        closed = self.details()["recent_resolved"][0]
        self.assertEqual(closed["resolution_source"], "reconciliation")

    def test_availability_before_inventory_is_reconciled(self):
        self.s.disconnected()
        self.s.connected()
        self.receive("plug/availability", b'{"state":"offline"}', retain=True)
        self.receive("bridge/state", b'online', retain=True)
        self.assertEqual(self.store.incident_history()[2], 0)
        self.receive("bridge/devices", inventory(), retain=True)
        self.assertEqual(self.store.incident_history()[2], 1)
        self.assertEqual(self.details()["incidents"][0]["started_at"], None)

    def test_partial_unknown_no_incident_does_not_claim_clean(self):
        self.receive("plug/availability", b'{"state":"online"}', retain=True)
        self.assertEqual(self.t.last(validity_topic("incidents")), "offline")
        self.assertFalse(self.details()["observation_complete"])

    def test_sqlite_identity_survives_rename_without_duplicate(self):
        self.receive("plug/availability", b'{"state":"offline"}', retain=True)
        first_id = self.details()["incidents"][0]["incident_id"]
        renamed = json.dumps([
            {"type": "Router", "ieee_address": IEEE1, "friendly_name": "renamed_plug"},
            {"type": "EndDevice", "ieee_address": IEEE2, "friendly_name": "battery"},
        ]).encode()
        self.receive("bridge/devices", renamed, retain=True)
        self.receive("renamed_plug/availability", b'{"state":"offline"}', retain=True)
        self.assertEqual(self.details()["incidents"][0]["incident_id"], first_id)
        self.assertEqual(self.details()["incidents"][0]["name"], "renamed_plug")

    def test_recorder_incident_histories_are_not_dynamic_sensor_attributes(self):
        from zigbee_monitor.discovery import build_discovery
        comps = build_discovery("0.1.7")["components"]
        self.assertNotIn("json_attributes_topic", comps["incidents"])
        self.assertIn("json_attributes_topic", comps["incidents_details"])


if __name__ == "__main__":
    unittest.main()
