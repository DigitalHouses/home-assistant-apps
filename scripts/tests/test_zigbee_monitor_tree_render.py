"""Render real Zigbee Monitor Lovelace Jinja, not merely search YAML text.

One root backslash, followed by every Z2M and every dedicated repeater as
independent first-level ASCII branches. No YAML/HTML tree rewrite allowed.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "digitalhouses_zigbee_monitor_app/examples/lovelace/dh_zigbee_monitor_app_dashboard.yaml"


class ZigbeeTreeRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dashboard = yaml.safe_load(DASHBOARD.read_text(encoding="utf-8"))
        cards = [card for section in dashboard["sections"] for card in section["cards"]]
        index = next(i for i, card in enumerate(cards) if card.get("type") == "heading"
                     and card.get("heading") == "Дерево Zigbee2MQTT")
        cls.template = cards[index + 1]["content"]
        assert cards[index + 1]["type"] == "markdown"
        standalone = yaml.safe_load((DASHBOARD.parent /
            "dh_zigbee_monitor_app_tree_ru.yaml").read_text(encoding="utf-8"))
        assert standalone == cards[index + 1], "standalone tree diverges from Dashboard"
        cls.engine = Environment(trim_blocks=True, lstrip_blocks=True)

    @staticmethod
    def network(name, problems=None, unknown=None):
        return {
            "name": name, "agent_name": "WRONG DISPLAY OVERRIDE",
            "network_id": "INTERNAL_ID_NOT_FOR_HEADER",
            "infrastructure": {
                "coordinator_ieee": "0x00124b002e1330dd", "connection": "usb",
                "serial_port": "/dev/ttyUSB0", "serial_adapter": "zstack",
                "coordinator_type": "ZStack3x0", "firmware_revision": "20240710",
                "z2m_version": "2.14.2", "channel": 11, "pan_id": 8099,
            },
            "agent_policy": {
                "hardware_model": "ZigStar UZG-01", "critical": True,
                "addon_slug": "", "binding_state": "unverified",
                "power_switch": "", "healer_method": "disabled",
            },
            "management_ip": "192.168.11.40", "ping": "reachable",
            "status": "online", "devices": 7, "online": 6, "offline": 1,
            "availability_unknown": 0, "rpm": 17.4, "threshold": 10,
            "infrastructure_seen": True, "problem_active": problems or [],
            "problem_unknown": unknown or [],
        }

    @staticmethod
    def repeater(name):
        return {
            "name": name, "ieee": "0x00158d0000000001", "model": "ZigStar-01",
            "critical": False, "discovered": True, "network_name": "zigbee2mqtt",
            "management_ip": "", "ping": "not_configured", "power_switch": "",
        }

    def render(self, networks, repeaters, network_state="ready"):
        return self.engine.from_string(self.template).render(
            states=lambda entity: network_state if entity.endswith("networks_details")
            else "ready",
            state_attr=lambda entity, key: networks if key == "networks" else
            repeaters if key == "repeaters" else None,
        )

    def tree_lines(self, rendered):
        self.assertIn("<pre>", rendered)
        self.assertIn("</pre>", rendered)
        source = rendered.split("<pre>", 1)[1].split("</pre>", 1)[0]
        self.assertNotIn("\n\n", source)
        return source.splitlines()

    def test_three_z2m_and_five_repeaters_are_eight_root_branches(self):
        networks = [self.network(name) for name in (
            "zigbee2mqtt", "zigbee2mqtt_office", "zigbee2mqtt_floor2"
        )]
        repeaters = [self.repeater("Repeater " + str(i)) for i in range(5)]
        lines = self.tree_lines(self.render(networks, repeaters))
        self.assertEqual(lines[0], "\\")
        branches = [line for line in lines[1:] if re.match(r"^[├└]─ ", line)]
        self.assertEqual(len(branches), 8)
        self.assertEqual(branches[:3], [
            "├─ 🟩 zigbee2mqtt", "├─ 🟩 zigbee2mqtt_office",
            "├─ 🟩 zigbee2mqtt_floor2",
        ])
        self.assertEqual(branches[3:7], [
            "├─ 📡 Repeater 0", "├─ 📡 Repeater 1",
            "├─ 📡 Repeater 2", "├─ 📡 Repeater 3",
        ])
        self.assertEqual(branches[7], "└─ 📡 Repeater 4")
        self.assertTrue(any(x.startswith("│  ├─ 🏷️ Тип: 👑 Координатор") for x in lines))
        self.assertFalse(any("IEEE:" in x for x in lines))
        self.assertNotIn("INTERNAL_ID_NOT_FOR_HEADER", "\n".join(lines))
        self.assertNotIn("WRONG DISPLAY OVERRIDE", "\n".join(lines))
        self.assertNotIn("\nРепитеры\n", "\n".join(lines))

    def test_single_z2m_ends_root_without_repeaters(self):
        rendered = self.render([self.network("zigbee2mqtt")], [])
        lines = self.tree_lines(rendered)
        self.assertEqual(lines[:2], ["\\", "└─ 🟩 zigbee2mqtt"])
        self.assertTrue(any(x.startswith("   ├─ 🏷️ Тип: 👑 Координатор") for x in lines))
        self.assertIn("💓 Pulse: 17.4 MPM (10)", rendered)
        self.assertIn("🌐 IP: 192.168.11.40 ✅", rendered)
        self.assertIn("🔌 Status: online", rendered)
        self.assertIn("📦 Devices: 7 (6 online, 1 offline)", rendered)
        self.assertIn("💊 Healer: OFF", rendered)
        self.assertEqual(len(lines), 9, "one root, one node, seven compact lines")

    def test_repeaters_alone_have_one_shared_root(self):
        lines = self.tree_lines(self.render([], [
            self.repeater("Hall"), self.repeater("Garage")
        ], network_state="unavailable"))
        self.assertEqual(lines[0], "\\")
        branches = [x for x in lines if re.match(r"^[├└]─ ", x)]
        self.assertEqual(branches, ["├─ 📡 Hall", "└─ 📡 Garage"])
        self.assertTrue(any(x.startswith("│  ├─ 🏷️ Тип: 📡 Репитер") for x in lines))
        self.assertTrue(any(x.startswith("   ├─ 🏷️ Тип: 📡 Репитер") for x in lines))
        self.assertEqual(len(lines), 13, "one root, two repeaters with five lines each")

    def test_unavailable_networks_cannot_render_stale_network_list(self):
        result = self.render([self.network("STALE NETWORK")],
                             [self.repeater("Hall")], network_state="unavailable")
        self.assertNotIn("STALE NETWORK", result)
        self.assertIn("└─ 📡 Hall", result)

    def test_compact_card_has_seven_primary_fields_per_coordinator(self):
        lines = self.tree_lines(self.render([self.network("zigbee2mqtt")], []))
        self.assertEqual(len(lines), 9)
        labels = [
            "🏷️ Тип:", "⚙️ Железо:", "🌐 IP:", "📦 Devices:",
            "💊 Healer:", "🔌 Status:", "💓 Pulse:",
        ]
        for item, label in zip(lines[2:], labels):
            self.assertIn(label, item)
        for forbidden in ("Firmware:", "IEEE:", "PAN:", "Adapter:",
                          "Supervisor:", "Питание:", "Info:",
                          "network_id", "Причины:"):
            self.assertNotIn(forbidden, "\\n".join(lines))

    def test_ping_no_answer_is_uncertain_not_device_failure(self):
        n = self.network("zigbee2mqtt")
        n["ping"] = "no_response"
        n["management_ip"] = "192.168.11.40"
        lines = self.tree_lines(self.render([n], []))
        self.assertIn("🌐 IP: 192.168.11.40 ❓ нет ответа", "\\n".join(lines))
        self.assertTrue(lines[1].startswith("└─ 🟩"))
        n["rpm"] = None
        n["threshold"] = None
        rendered = self.render([n], [])
        self.assertIn("❓ Pulse: — MPM (—)", rendered)
        self.assertNotIn("💓 Pulse: — MPM", rendered)

    def test_empty_network_and_repeater_lists(self):
        result = self.render([], [])
        self.assertNotIn("<pre>", result)
        self.assertIn("пока не обнаружены", result)

    def test_problem_details_keep_children_under_correct_parent(self):
        result = self.render([self.network(
            "zigbee2mqtt", ["mqtt_traffic_low"], ["devices_offline"]
        )], [])
        self.assertIn("🟥 zigbee2mqtt", result)
        self.assertIn("💔 Pulse: 17.4 MPM (10)", result)
        self.assertIn("🔌 Status: online", result)
        self.assertIn("📦 Devices: 7 (6 online, 1 offline)", result)
        self.assertNotIn("├─ ON:", result)
        self.assertNotIn("└─ ?:", result)
        self.assertNotIn("<details", result)
        self.assertNotIn("<table", result)


if __name__ == "__main__":
    unittest.main()
