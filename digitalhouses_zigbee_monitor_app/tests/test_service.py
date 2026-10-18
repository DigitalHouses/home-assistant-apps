"""MQTT Discovery, Recorder isolation, reconnect and live-data publication tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.discovery import (
    APP_AVAILABILITY, DETAILS, DISCOVERY, HISTORY, ROOT,
    build_discovery, state_topic, validity_topic,
)
from zigbee_monitor.service import MonitorService

IEEE = "0x00158d0000000001"


class FakeTransport:
    def __init__(self):
        self.published: list[tuple[str, str, bool]] = []
        self.subscribed: list[str] = []

    def publish(self, topic: str, payload: str, retain: bool) -> bool:
        self.published.append((topic, payload, retain))
        return True

    def subscribe(self, topic: str) -> bool:
        self.subscribed.append(topic)
        return True

    def last(self, topic: str) -> str | None:
        rows = [payload for key, payload, _ in self.published if key == topic]
        return rows[-1] if rows else None


def inventory(name: str = "Термостат") -> bytes:
    return json.dumps([{
        "type": "Router", "ieee_address": IEEE,
        "friendly_name": name,
        "definition": {"model": "TRV", "vendor": "Test"},
    }]).encode("utf-8")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = [600.0]
        self.t = FakeTransport()
        networks = parse_networks([{
            "network_id": "floor_1", "name": "Этаж 1",
            "base_topic": "zigbee2mqtt_1",
        }])
        self.store = ActivityStore(Path(tmp.name) / "runtime.sqlite")
        self.addCleanup(self.store.close)
        self.s = MonitorService(
            ZigbeeMonitor(networks), self.store,
            publish=self.t.publish, subscribe=self.t.subscribe,
            version="0.1.0", now=lambda: self.clock[0],
        )

    def receive(self, topic, payload, **kwargs):
        return self.s.receive("zigbee2mqtt_1/" + topic, payload, **kwargs)

    def test_discovery_history_sensors_have_no_dynamic_attributes(self):
        components = build_discovery("0.1.0")["components"]
        for key in HISTORY:
            sensor = components[key]
            self.assertEqual(sensor["default_entity_id"], "sensor.dh_zigbee_monitor_app_" + key)
            self.assertNotIn("json_attributes_topic", sensor)
            self.assertNotIn("json_attributes_template", sensor)
            self.assertEqual(len(sensor["availability"]), 2)
        for key in DETAILS:
            self.assertIn("json_attributes_topic", components[key])
            self.assertEqual(components[key]["state_topic"], state_topic(key))
        self.assertEqual(components["card"]["default_entity_id"],
                         "sensor.dh_zigbee_monitor_app_card")
        self.assertEqual(components["refresh"]["command_topic"], ROOT + "/command/refresh")

    def test_connect_starts_unknown_not_zero_and_reads_only(self):
        self.s.connected()
        self.assertEqual(self.t.last(validity_topic("devices")), "offline")
        self.assertEqual(self.t.last(validity_topic("offline")), "offline")
        self.assertEqual(self.t.last(state_topic("networks")), "1")
        self.assertIsNone(self.t.last(state_topic("devices")))
        self.assertEqual(self.t.last(APP_AVAILABILITY), "online")
        self.assertIn("zigbee2mqtt_1/#", self.t.subscribed)
        self.assertIsNotNone(self.t.last(DISCOVERY))

    def test_source_transitions_reconcile_before_scalar_available(self):
        self.s.connected()
        self.receive("bridge/devices", inventory(), retain=True)
        self.assertEqual(self.t.last(validity_topic("devices")), "offline")
        self.receive("bridge/state", b'{"state":"online"}', retain=True)
        self.assertEqual(self.t.last(state_topic("devices")), "1")
        self.assertEqual(self.t.last(validity_topic("devices")), "online")
        self.assertEqual(self.t.last(validity_topic("offline")), "offline")
        self.receive("Термостат/availability", b'{"state":"offline"}', retain=True)
        self.assertEqual(self.t.last(state_topic("offline")), "1")
        self.assertEqual(self.t.last(validity_topic("offline")), "online")
        info = json.loads(self.t.last(state_topic("offline_details")))
        self.assertIsNone(info["devices"][0]["offline_since"])
        # A retained offline observation cannot manufacture start time.
        self.receive("Термостат/availability", b'{"state":"online"}')
        self.assertEqual(self.t.last(state_topic("offline")), "0")
        self.assertEqual(self.t.last(state_topic("offline_details")) is not None, True)
        self.receive("bridge/state", b'{"state":"offline"}')
        self.assertEqual(self.t.last(validity_topic("offline")), "offline")
        self.assertEqual(self.t.last(validity_topic("devices")), "offline")

    def test_reconnect_does_not_reuse_cached_state(self):
        self.s.connected()
        self.receive("bridge/devices", inventory(), retain=True)
        self.receive("bridge/state", b"online", retain=True)
        self.receive("Термостат/availability", b'{"state":"online"}', retain=True)
        self.assertEqual(self.t.last(validity_topic("devices")), "online")
        self.s.disconnected()
        self.s.connected()
        self.assertEqual(self.t.last(validity_topic("devices")), "offline")
        self.assertEqual(self.t.last(validity_topic("offline")), "offline")
        self.assertIsNone(self.s.monitor.total_devices())
        self.receive("bridge/devices", inventory(), retain=True)
        self.assertEqual(self.t.last(validity_topic("devices")), "offline")

    def test_rename_updates_display_without_resetting_history(self):
        self.s.connected()
        self.receive("bridge/devices", inventory(), retain=True)
        self.receive("bridge/state", b"online", retain=True)
        self.receive("Термостат", b'{"temperature":21}', observed_at=600)
        self.clock[0] = 660
        self.s.tick()
        self.receive("bridge/devices", inventory("Комната"), retain=True)
        self.receive("Комната", b'{"temperature":21}', observed_at=660)
        self.clock[0] = 720
        self.s.tick()
        rows = self.store.top(from_epoch=600, until_epoch=720)
        self.assertEqual(rows[0]["messages"], 2)
        self.assertEqual(rows[0]["name"], "Комната")
        self.assertEqual(rows[0]["ieee_address"], IEEE)

    def test_retained_devices_are_not_ranked_and_no_unproven_zero(self):
        self.s.connected()
        self.receive("bridge/devices", inventory(), retain=True)
        self.receive("bridge/state", b"online", retain=True)
        self.receive("Термостат", b'{"temperature":20}', retain=True)
        self.clock[0] = 660
        self.s.tick()
        self.assertIsNone(self.store.first_bucket())
        self.assertEqual(self.t.last(validity_topic("top_1h_details")), "offline")
        self.assertEqual(self.t.last(validity_topic("messages_rate_5m")), "offline")

    def test_manual_refresh_resubscribes_and_requires_inventory(self):
        self.s.connected()
        self.assertEqual(self.s.receive(ROOT + "/command/refresh", b"PRESS"), "refresh_command")
        self.assertIn("zigbee2mqtt_1/bridge/devices", self.t.subscribed)
        self.assertEqual(json.loads(self.t.last(state_topic("card")))["state"], "running")
        self.receive("bridge/devices", inventory(), retain=True)
        self.assertEqual(json.loads(self.t.last(state_topic("card")))["state"], "running")
        self.assertEqual(json.loads(self.t.last(state_topic("refresh_state")))["state"], "updating")
        self.receive("bridge/state", b"online", retain=True)
        # Inventory and confirmed bridge state are enough: per-device Z2M
        # availability may legitimately be disabled.
        self.assertEqual(json.loads(self.t.last(state_topic("card")))["state"], "success")
        self.assertEqual(self.t.last(validity_topic("offline")), "offline")
        self.assertEqual(json.loads(self.t.last(state_topic("refresh_state")))["state"], "idle")
        self.assertIsNotNone(self.t.last(state_topic("last_refresh")))

    def test_refresh_times_out_instead_of_fake_success(self):
        self.s.connected()
        self.s.receive(ROOT + "/command/refresh", b"PRESS")
        self.clock[0] += 16
        self.s.tick()
        card = json.loads(self.t.last(state_topic("card")))
        self.assertEqual(card["state"], "error")
        self.assertIn("inventory", card["error"])

    def test_inventory_exposes_unavailable_device_reason_without_recorder_attributes(self):
        self.s.connected()
        self.receive("bridge/devices", inventory(), retain=True)
        self.receive("bridge/state", b"online", retain=True)
        details = json.loads(self.t.last(state_topic("inventory_details")))
        self.assertEqual(details["total"], 1)
        self.assertEqual(details["availability_unknown"], 1)
        self.assertFalse(details["availability_complete"])
        d = details["devices"][0]
        self.assertEqual(d["ieee_address"], IEEE)
        self.assertEqual(d["availability"], "unknown")
        self.assertEqual(d["availability_reason"], "availability_not_reported")
        self.assertEqual(d["availability_reason_label"], "Нет сообщения availability")
        self.assertEqual(self.t.last(validity_topic("offline")), "offline")
        self.receive("Термостат/availability", b'{"state":"online"}', retain=True)
        details = json.loads(self.t.last(state_topic("inventory_details")))
        self.assertEqual(details["availability_unknown"], 0)
        self.assertTrue(details["availability_complete"])
        self.assertEqual(details["devices"][0]["availability_label"], "В сети")
        self.assertEqual(self.t.last(state_topic("offline")), "0")

    def test_manual_refresh_without_optional_availability_succeeds_and_preserves_unknown(self):
        self.s.connected()
        self.s.receive(ROOT + "/command/refresh", b"PRESS")
        self.receive("bridge/devices", inventory(), retain=True)
        self.assertIsNone(self.t.last(state_topic("last_refresh")))
        self.receive("bridge/state", b"online", retain=True)
        self.assertEqual(json.loads(self.t.last(state_topic("card")))["state"], "success")
        self.assertEqual(json.loads(self.t.last(state_topic("refresh_state")))["state"], "idle")
        self.assertIsNotNone(self.t.last(state_topic("last_refresh")))
        self.assertEqual(self.t.last(validity_topic("offline")), "offline")
        # The confirmed offline list is valid on a live bridge even when some
        # peers have unknown availability. Only the scalar zero stays unknown.
        self.assertEqual(self.t.last(validity_topic("offline_details")), "online")
        offline_details = json.loads(self.t.last(state_topic("offline_details")))
        self.assertEqual(offline_details["devices"], [])
        self.assertFalse(offline_details["availability_complete"])
        details = json.loads(self.t.last(state_topic("inventory_details")))
        self.assertFalse(details["availability_complete"])
        self.assertEqual(details["availability_unknown"], 1)
        self.assertEqual(details["devices"][0]["availability_reason"], "availability_not_reported")
        # No delayed error after the successful refresh.
        self.clock[0] += 30
        self.s.tick()
        self.assertEqual(json.loads(self.t.last(state_topic("card")))["state"], "idle")

    def test_refresh_waits_for_actual_bridge_state_even_when_inventory_arrives(self):
        self.s.connected()
        # Existing cached bridge state must not satisfy a NEW manual refresh.
        self.receive("bridge/devices", inventory(), retain=True)
        self.receive("bridge/state", b"online", retain=True)
        self.s.receive(ROOT + "/command/refresh", b"PRESS")
        self.receive("bridge/devices", inventory(), retain=True)
        self.assertEqual(json.loads(self.t.last(state_topic("card")))["state"], "running")
        self.assertIsNone(self.t.last(state_topic("last_refresh")))
        self.clock[0] += 16
        self.s.tick()
        self.assertEqual(json.loads(self.t.last(state_topic("card")))["state"], "error")
        self.assertIn("bridge:", json.loads(self.t.last(state_topic("card")))["error"])
        self.assertIsNone(self.t.last(state_topic("last_refresh")))

    def test_refresh_reports_offline_bridge_as_error_not_false_success(self):
        self.s.connected()
        self.s.receive(ROOT + "/command/refresh", b"PRESS")
        self.receive("bridge/devices", inventory(), retain=True)
        self.receive("bridge/state", b"offline", retain=True)
        self.assertEqual(json.loads(self.t.last(state_topic("card")))["state"], "running")
        self.clock[0] += 16
        self.s.tick()
        self.assertEqual(json.loads(self.t.last(state_topic("card")))["state"], "error")
        self.assertIsNone(self.t.last(state_topic("last_refresh")))

    def test_refresh_disallows_duplicate_work_and_success_visible_five_seconds(self):
        self.s.connected()
        self.s.receive(ROOT + "/command/refresh", b"PRESS")
        before = len(self.t.subscribed)
        self.s.receive(ROOT + "/command/refresh", b"PRESS")
        self.assertEqual(len(self.t.subscribed), before)
        self.receive("bridge/devices", inventory(), retain=True)
        self.receive("bridge/state", b"online", retain=True)
        self.receive("Термостат/availability", b'{"state":"online"}', retain=True)
        self.assertEqual(json.loads(self.t.last(state_topic("card")))["state"], "success")
        self.clock[0] += 4
        self.s.tick()
        self.assertEqual(json.loads(self.t.last(state_topic("card")))["state"], "success")
        self.clock[0] += 2
        self.s.tick()
        self.assertEqual(json.loads(self.t.last(state_topic("card")))["state"], "idle")

    def test_refresh_contract_is_recorder_excluded(self):
        c = build_discovery("0.1.3")["components"]["refresh_state"]
        self.assertEqual(c["default_entity_id"], "sensor.dh_zigbee_monitor_app_refresh_state")
        self.assertEqual(c["json_attributes_topic"], state_topic("refresh_state"))
        self.assertEqual(c["value_template"], "{{ value_json.state }}")

    def test_retained_command_is_ignored(self):
        self.s.connected()
        self.s.receive(ROOT + "/command/refresh", b"PRESS", retain=True)
        self.assertEqual(json.loads(self.t.last(state_topic("card")))["state"], "idle")

    def test_rate_requires_full_uninterrupted_five_minutes(self):
        self.s.connected()
        self.receive("bridge/devices", inventory(), retain=True)
        self.receive("bridge/state", b"online", retain=True)
        self.receive("Термостат/availability", b'{"state":"online"}', retain=True)
        self.receive("Термостат", b"{}", observed_at=600)
        self.clock[0] = 660
        self.s.tick()
        self.assertEqual(self.t.last(validity_topic("messages_rate_5m")), "offline")
        self.clock[0] = 960
        self.s.tick()
        self.assertEqual(self.t.last(validity_topic("messages_rate_5m")), "online")
        self.assertEqual(self.t.last(state_topic("messages_rate_5m")), "0.0")


if __name__ == "__main__":
    unittest.main()
