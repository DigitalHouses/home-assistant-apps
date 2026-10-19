"""Independent optional coordinator/repeater Options with no Zigbee/Healer actions."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.agent_options import (
    is_recognized_repeater, management_address, merge_new_discoveries,
    normalize_registry, ping_management_ip,
)
from zigbee_monitor.core import Device
from zigbee_monitor.discovery import DISCOVERY, ROOT
from zigbee_monitor.service import MonitorService

COORD = "0x00158d0000000001"
REP = "0x00158d0000000002"
PLUG = "0x00158d0000000003"


class AgentOptionsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "activity.sqlite"
        self.store = ActivityStore(self.path)
        self.addCleanup(self.store.close)
        self.network, _ = self.store.register_network(COORD, "zigbee2mqtt", observed_at=1)
        self.published = []
        self.svc = MonitorService(
            ZigbeeMonitor(parse_networks([
                {"network_id": self.network.network_id,
                 "base_topic": "zigbee2mqtt", "name": "Office"},
            ])),
            self.store,
            publish=lambda topic, body, retain: (
                self.published.append((topic, body, retain)) or True
            ),
            subscribe=lambda _: True,
            version="0.1.11", now=lambda: 10000.0,
        )
        self.svc.connected()

    def last(self, topic):
        return next((body for t, body, _ in reversed(self.published)
                     if t == topic), None)

    def tree(self):
        return json.loads(self.last(f"{ROOT}/state/networks_details"))["networks"][0]

    def test_first_boot_no_config_is_valid_and_controls_are_removed(self):
        comps = json.loads(self.last(DISCOVERY))["components"]
        self.assertIn("repeaters_details", comps)
        self.assertFalse(any("_agent_" in name for name in comps))
        self.assertEqual(normalize_registry({}),
                         {"coordinators": [], "repeaters": []})
        self.assertFalse(self.tree()["agent_policy"]["healer_enabled"])
        self.assertEqual(self.tree()["ping"], "not_configured")
        self.assertEqual(self.svc.agent_snapshot()[0][0]["ieee"], COORD)

    def test_auto_fill_only_recognized_routers_and_idempotent(self):
        recognized = Device(REP, self.network.network_id, "Hall",
                            "ZigStar-01", "ZigStar", "Router")
        lamp = Device(PLUG, self.network.network_id, "Lamp", "BULB1",
                      "Generic", "Router")
        self.assertTrue(is_recognized_repeater(recognized))
        self.assertFalse(is_recognized_repeater(lamp))
        self.assertFalse(is_recognized_repeater(
            Device(REP, self.network.network_id, "Hall", "ZigStar-01",
                   "ZigStar", "EndDevice")))
        current = {"telemetry_enabled": True, "log_level": "info",
                   "coordinators": [], "repeaters": []}
        coords, _, legacy = self.svc.agent_snapshot()
        new, changed = merge_new_discoveries(
            current, coords,
            [{"ieee": REP, "name": "Hall", "model": "ZigStar-01",
              "recognized": True},
             {"ieee": PLUG, "name": "Lamp", "recognized": False}],
            legacy=legacy,
        )
        self.assertTrue(changed)
        self.assertEqual(new["coordinators"][0]["ieee"], COORD)
        self.assertEqual([r["ieee"] for r in new["repeaters"]], [REP])
        newer, changed = merge_new_discoveries(new, coords, [])
        self.assertFalse(changed)
        self.assertEqual(new, newer)

    def test_existing_overrides_and_legacy_migration(self):
        cur = {"coordinators": [{"ieee": COORD, "name": "USER NAME",
                                 "critical": True}], "repeaters": []}
        nxt, changed = merge_new_discoveries(
            cur, [{"ieee": COORD, "name": "NEW Z2M NAME"}], [],
        )
        self.assertFalse(changed)
        self.assertEqual(nxt, cur)
        old = self.store.network_agent_policy(self.network.network_id)
        self.assertFalse(old["critical"])
        self.store.update_network_agent_policy(
            self.network.network_id, key="critical", value=True,
        )
        self.store.update_network_agent_policy(
            self.network.network_id, key="display_name", value="OLD NAME",
        )
        legacy = {self.network.network_id:
                  self.store.network_agent_policy(self.network.network_id)}
        nxt, changed = merge_new_discoveries(
            {"coordinators": [], "repeaters": []},
            self.svc.agent_snapshot()[0], [], legacy,
        )
        self.assertTrue(changed)
        self.assertEqual(nxt["coordinators"][0]["name"], "OLD NAME")
        self.assertTrue(nxt["coordinators"][0]["critical"])

    def test_configured_tree_and_repeater_ping_status(self):
        settings = {
            "coordinators": [{
                "ieee": COORD, "name": "Techroom USB", "model": "ZigStar-01",
                "critical": True, "management_ip": "192.168.11.40",
                "addon_slug": "45df7312_zigbee2mqtt",
                "healer_method": "addon_restart",
            }],
            "repeaters": [{
                "ieee": REP, "name": "Hall",
                "management_ip": "192.168.11.41",
            }],
        }
        self.svc.set_agent_options(settings)
        self.svc.set_ping_results({COORD: "reachable", REP: "no_response"})
        self.assertEqual(self.tree()["agent_name"], "Techroom USB")
        self.assertEqual(self.tree()["ping"], "reachable")
        self.assertTrue(self.tree()["agent_policy"]["critical"])
        self.assertEqual(self.tree()["agent_policy"]["binding_state"], "unverified")
        self.assertFalse(self.tree()["agent_policy"]["healer_enabled"])
        rows = json.loads(self.last(f"{ROOT}/state/repeaters_details"))["repeaters"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ieee"], REP)
        self.assertEqual(rows[0]["ping"], "no_response")
        self.assertFalse(rows[0]["discovered"])
        self.assertFalse(rows[0]["binding_verified"])
        self.assertEqual(self.svc.agent_ping_targets(),
                         {COORD: "192.168.11.40", REP: "192.168.11.41"})
        self.assertEqual(
            self.svc.receive(f"{ROOT}/command/agent/{self.network.network_id}/critical", b"ON"),
            "agent_setting_ignored",
        )

    def test_invalid_ip_never_prevents_normal_startup_or_fake_ping(self):
        self.assertIsNone(management_address("https://secret.example/token"))
        self.assertIsNone(management_address("127.0.0.1"))
        self.assertEqual(ping_management_ip(""), "not_configured")
        self.assertEqual(ping_management_ip("abc"), "invalid")
        self.svc.set_agent_options({
            "coordinators": [{"ieee": COORD, "management_ip": "bad host"}]
        })
        self.assertEqual(self.tree()["ping"], "invalid")
        self.assertNotIn(COORD, self.svc.agent_ping_targets())

    def test_ping_check_only_indicates_reachability(self):
        class Reply:
            returncode = 0
            stderr = b""
        with patch("zigbee_monitor.agent_options.subprocess.run", return_value=Reply()) as run:
            self.assertEqual(ping_management_ip("192.168.11.42"), "reachable")
            self.assertEqual(run.call_args.args[0][-1], "192.168.11.42")
        Reply.returncode = 1
        with patch("zigbee_monitor.agent_options.subprocess.run", return_value=Reply()):
            self.assertEqual(ping_management_ip("192.168.11.42"), "no_response")


if __name__ == "__main__":
    unittest.main()
