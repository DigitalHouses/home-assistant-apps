"""Passport-free agent policy E2E: HA MQTT controls, SQLite and no execution."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.discovery import DISCOVERY, ROOT
from zigbee_monitor.service import MonitorService

COORD1 = "0x00158d0000000001"
COORD2 = "0x00158d0000000002"


class AgentPolicyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "activity.sqlite"
        self.store = ActivityStore(self.path)
        self.addCleanup(self.store.close)
        self.first, _ = self.store.register_network(
            COORD1, "zigbee2mqtt", observed_at=1,
        )
        self.second, _ = self.store.register_network(
            COORD2, "z2m/other", observed_at=1,
        )
        self.published = []
        self.subscribed = []
        self.svc = MonitorService(
            ZigbeeMonitor(parse_networks([
                {"network_id": self.first.network_id,
                 "base_topic": "zigbee2mqtt", "name": "Main"},
                {"network_id": self.second.network_id,
                 "base_topic": "z2m/other", "name": "Other"},
            ])),
            self.store,
            publish=lambda topic, data, retain: (
                self.published.append((topic, data, retain)) or True
            ),
            subscribe=lambda topic: (self.subscribed.append(topic) or True),
            version="0.1.10", now=lambda: 10000.0,
        )
        self.svc.connected()

    def command(self, nid, field, payload, **kwargs):
        return self.svc.receive(
            f"{ROOT}/command/agent/{nid}/{field}", payload, **kwargs
        )

    def last(self, topic):
        return next((body for t, body, retain in reversed(self.published)
                     if t == topic), None)

    def test_discovery_has_full_agent_controls_no_legacy_passports(self):
        discovery = json.loads(self.last(DISCOVERY))
        parts = discovery["components"]
        for network in (self.first, self.second):
            nid = network.network_id
            for field in ("display_name", "hardware_model", "management_host",
                          "addon_slug", "power_switch"):
                c = parts[f"{nid}_agent_{field}"]
                self.assertEqual(c["platform"], "text")
                self.assertEqual(c["command_topic"], f"{ROOT}/command/agent/{nid}/{field}")
            self.assertEqual(parts[f"{nid}_agent_critical"]["platform"], "switch")
            method = parts[f"{nid}_agent_healer_method"]
            self.assertEqual(method["platform"], "select")
            self.assertEqual(method["options"],
                             ["disabled", "addon_restart", "power_cycle"])
            self.assertEqual(
                self.last(f"{ROOT}/settings/{nid}/agent/healer_method"), "disabled",
            )
            self.assertEqual(self.last(f"{ROOT}/settings/{nid}/agent/critical"), "OFF")
        self.assertNotIn("passport", json.dumps(discovery).lower())

    def test_save_isolated_field_policy_without_actions(self):
        nid = self.first.network_id
        cases = [
            ("display_name", "KraftOffice Floor 1"),
            ("hardware_model", "ZigStar-01"),
            ("management_host", "192.168.1.41"),
            ("critical", "ON"),
            ("healer_method", "power_cycle"),
            ("power_switch", "switch.ps308g0000244100cd0mmvqbb_1_switch"),
            ("addon_slug", "45df7312_zigbee2mqtt"),
        ]
        for field, value in cases:
            with self.subTest(field=field):
                self.assertEqual(
                    self.command(nid, field, value.encode()), "agent_setting_updated",
                )
        policy = self.store.network_agent_policy(nid)
        self.assertEqual(policy["display_name"], "KraftOffice Floor 1")
        self.assertTrue(policy["critical"])
        self.assertEqual(policy["management_host"], "192.168.1.41")
        self.assertEqual(policy["healer_method"], "power_cycle")
        self.assertEqual(self.store.network_agent_policy(self.second.network_id)
                         ["healer_method"], "disabled")
        tree = json.loads(self.last(f"{ROOT}/state/networks_details"))["networks"]
        agent = next(n for n in tree if n["network_id"] == nid)
        self.assertEqual(agent["agent_name"], "KraftOffice Floor 1")
        self.assertEqual(agent["agent_policy"]["binding_state"], "unverified")
        self.assertFalse(agent["agent_policy"]["healer_enabled"])
        self.assertFalse(agent["agent_policy"]["binding_verified"])
        self.assertTrue(all(
            not t.startswith("zigbee2mqtt/bridge/request")
            and t != "homeassistant/service/hassio/app_restart"
            for t, _, _ in self.published
        ))
        # Database remains the source of truth across process restarts.
        with ActivityStore(self.path) as restored:
            self.assertEqual(restored.network_agent_policy(nid), policy)

    def test_missing_binding_and_unsupported_commands_are_fail_closed(self):
        nid = self.first.network_id
        self.command(nid, "healer_method", b"addon_restart")
        row = json.loads(self.last(f"{ROOT}/state/networks_details"))["networks"][0]
        self.assertEqual(row["agent_policy"]["binding_state"], "missing_binding")
        for field, body in (
            ("critical", b"TRUE"),
            ("healer_method", b"reboot"),
            ("addon_slug", b"evil/name"),
            ("power_switch", b"script.run"),
            ("management_host", b"https://credentials.local/x"),
            ("display_name", b"bad\nname"),
            ("not_a_field", b"on"),
        ):
            with self.subTest(field=field):
                self.assertEqual(self.command(nid, field, body),
                                 "agent_setting_ignored")
        self.assertEqual(self.command(nid, "critical", b"ON", retain=True),
                         "agent_setting_ignored")
        self.assertEqual(self.command("fake", "critical", b"ON"),
                         "agent_setting_ignored")
        self.assertFalse(self.store.network_agent_policy(nid)["critical"])
        self.assertEqual(self.command(nid, "healer_method", b"disabled"),
                         "agent_setting_updated")
        self.assertEqual(self.command(nid, "display_name", b""),
                         "agent_setting_updated")
        self.assertEqual(self.store.network_agent_policy(nid)["display_name"], "")


if __name__ == "__main__":
    unittest.main()
