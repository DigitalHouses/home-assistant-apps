"""Read-only Zigbee2MQTT availability/source machine-event contract tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.discovery import (
    EVENT_TOPIC, EVENT_TYPES, build_discovery, state_topic, validity_topic,
)
from zigbee_monitor.service import MonitorService

BASE = "zigbee2mqtt"
IEEE1 = "0x00158d0000000001"
IEEE2 = "0x00158d0000000002"


class Transport:
    def __init__(self):
        self.sent = []
        self.subscribed = []

    def publish(self, topic, payload, retain):
        self.sent.append((topic, payload, retain))
        return True

    def subscribe(self, topic):
        self.subscribed.append(topic)
        return True

    def last(self, topic):
        return next((payload for t, payload, _ in reversed(self.sent) if t == topic), None)

    def events(self):
        return [json.loads(payload) for topic, payload, _ in self.sent
                if topic == EVENT_TOPIC and json.loads(payload)["event_type"]
                not in ("network_fsm_changed","global_fsm_changed")]


class TransitionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.t = Transport()
        self.clock = [660.]
        self.store = ActivityStore(Path(temp.name) / "activity.sqlite")
        self.addCleanup(self.store.close)
        self.s = MonitorService(
            ZigbeeMonitor(parse_networks([{
                "network_id": "site_1", "base_topic": BASE, "name": "Living"
            }])),
            self.store, publish=self.t.publish, subscribe=self.t.subscribe,
            version="0.1.6", now=lambda: self.clock[0],
        )
        self.s.connected()
        self.receive("bridge/devices", json.dumps([
            {"type": "Router", "ieee_address": IEEE1, "friendly_name": "plug"},
            {"type": "EndDevice", "ieee_address": IEEE2, "friendly_name": "battery"},
        ]).encode(), retain=True)
        self.receive("bridge/state", b'{"state":"online"}', retain=True)

    def receive(self, topic, data, **kwargs):
        return self.s.receive(BASE + "/" + topic, data, **kwargs)

    def test_discovery_types_and_transient_transport(self):
        comp = build_discovery("0.1.6")["components"]["event"]
        self.assertEqual(comp["default_entity_id"], "event.dh_zigbee_monitor_app_event")
        self.assertEqual(comp["state_topic"], EVENT_TOPIC)
        self.assertEqual(set(comp["event_types"]), set(EVENT_TYPES))
        self.assertIn("availability", comp)
        self.assertFalse(self.t.events())

    def test_device_retain_is_baseline_live_transition_is_event(self):
        self.receive("plug/availability", b'{"state":"online"}', retain=True)
        self.assertFalse(self.t.events())
        self.receive("plug/availability", b'{"state":"online"}')
        self.assertFalse(self.t.events())
        self.clock[0] = 680.
        self.receive("plug/availability", b'{"state":"offline"}')
        events = self.t.events()
        self.assertEqual(len(events), 1)
        offline = events[0]
        self.assertEqual(offline["schema_version"], 1)
        self.assertEqual(offline["event_type"], "device_offline")
        self.assertEqual(offline["ieee_address"], IEEE1)
        self.assertEqual(offline["friendly_name"], "plug")
        self.assertEqual(offline["network_id"], "site_1")
        self.assertEqual(offline["previous_state"], "online")
        self.assertEqual(offline["current_state"], "offline")
        self.assertEqual(offline["severity"], "warning")
        self.assertEqual(offline["observed_at"], "1970-01-01T00:11:20+00:00")
        self.assertFalse([retain for t, _, retain in self.t.sent if t == EVENT_TOPIC][0])
        self.assertEqual(self.t.last(state_topic("offline")), "1")
        self.assertEqual(self.t.last(validity_topic("offline")), "online")
        details = json.loads(self.t.last(state_topic("offline_details")))
        self.assertEqual(details["total"], 1)
        self.assertFalse(details["availability_complete"])
        self.assertEqual(details["availability_unknown"], 1)
        self.assertEqual(details["devices"][0]["name"], "plug")
        self.assertEqual(details["devices"][0]["offline_since"], "1970-01-01T00:11:20+00:00")
        self.assertEqual(details["devices"][0]["ieee_address"], IEEE1)
        self.assertEqual(self.t.last(validity_topic("offline_details")), "online")
        self.clock[0] = 700.
        self.receive("plug/availability", b'{"state":"online"}')
        self.assertEqual(self.t.events()[-1]["event_type"], "device_online")
        self.assertEqual(self.t.events()[-1]["severity"], "info")
        self.assertEqual(self.t.last(validity_topic("offline")), "offline")
        self.assertEqual(json.loads(self.t.last(state_topic("offline_details")))["total"], 0)

    def test_never_publish_zero_when_devices_without_availability(self):
        self.assertIsNone(self.t.last(state_topic("offline")))
        self.assertEqual(self.t.last(validity_topic("offline")), "offline")
        self.assertEqual(self.t.last(validity_topic("offline_details")), "online")
        self.receive("battery/availability", b'{"state":"offline"}', retain=True)
        self.assertEqual(self.t.last(state_topic("offline")), "1")
        self.assertEqual(self.t.last(validity_topic("offline")), "online")
        self.assertEqual(self.t.events(), [])

    def test_z2m_source_transitions_do_not_create_device_floods(self):
        self.receive("plug/availability", b'{"state":"online"}', retain=True)
        self.receive("battery/availability", b'{"state":"online"}', retain=True)
        self.receive("bridge/state", b'{"state":"online"}')
        self.assertFalse(self.t.events())
        self.receive("bridge/state", b'{"state":"offline"}')
        event = self.t.events()[0]
        self.assertEqual(event["event_type"], "zigbee2mqtt_offline")
        self.assertEqual(event["base_topic"], BASE)
        self.assertEqual(event["network_id"], "site_1")
        self.assertEqual(event["previous_state"], "online")
        self.assertEqual(event["current_state"], "offline")
        self.assertEqual(self.t.last(validity_topic("offline")), "offline")
        network = json.loads(self.t.last(state_topic("networks_details")))
        self.assertEqual(network["networks"][0]["status"], "offline")
        self.receive("plug/availability", b'{"state":"offline"}')
        self.assertEqual(len(self.t.events()), 1)
        self.receive("bridge/state", b'{"state":"online"}')
        self.assertEqual([x["event_type"] for x in self.t.events()],
                         ["zigbee2mqtt_offline", "zigbee2mqtt_online"])
        self.receive("plug/availability", b'{"state":"online"}')
        self.assertEqual(len(self.t.events()), 2)

    def test_bootstrap_and_reconnect_never_replay_events(self):
        self.receive("plug/availability", b'{"state":"offline"}', retain=True)
        self.assertEqual(self.t.events(), [])
        self.s.disconnected()
        self.s.connected()
        self.receive("bridge/devices", json.dumps([
            {"type": "Router", "ieee_address": IEEE1, "friendly_name": "plug"}
        ]).encode(), retain=True)
        self.receive("bridge/state", b'{"state":"online"}', retain=True)
        self.receive("plug/availability", b'{"state":"offline"}', retain=True)
        self.assertEqual(self.t.events(), [])
        self.receive("plug/availability", b'{"state":"online"}')
        self.assertEqual([x["event_type"] for x in self.t.events()], ["device_online"])

    def test_initial_unretained_offline_does_not_invent_transition(self):
        self.receive("plug/availability", b'{"state":"offline"}')
        self.assertEqual(self.t.events(), [])
        self.assertEqual(self.t.last(state_topic("offline")), "1")

    def test_qos_duplicates_and_retained_transitions_are_not_events(self):
        self.receive("plug/availability", b'{"state":"online"}', retain=True)
        self.receive("plug/availability", b'{"state":"offline"}', dup=True)
        self.receive("plug/availability", b'{"state":"online"}', retain=True)
        self.assertEqual(self.t.events(), [])
        self.assertEqual(self.t.last(validity_topic("offline")), "offline")


if __name__ == "__main__":
    unittest.main()
