"""Dashboard assembly contract: no copied cards drifting from canonical sources."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1] / "examples" / "lovelace"


class DashboardTests(unittest.TestCase):
    def test_single_view_matches_operator_view_and_pve_layout(self):
        dashboard = yaml.safe_load((ROOT / "dh_aqara_switch_app_dashboard_ru.yaml").read_text())
        standalone = yaml.safe_load((ROOT / "dh_aqara_switch_app_view_ru.yaml").read_text())
        self.assertEqual(dashboard["title"], "DH Aqara Switch")
        self.assertEqual(len(dashboard["views"]), 1)
        self.assertEqual(dashboard["views"][0], standalone)
        view = standalone
        self.assertEqual(view["type"], "sections")
        self.assertEqual(view["max_columns"], 4)
        self.assertEqual(view["path"], "aqara")
        self.assertEqual([s["column_span"] for s in view["sections"]], [1, 1, 2])

        status, scan, tree = [s["cards"] for s in view["sections"]]
        self.assertEqual([c["type"] for c in status], [
            "heading", "custom:mushroom-template-card", "vertical-stack",
            "heading", "markdown"])
        self.assertEqual([c["type"] for c in scan], [
            "heading", "markdown", "custom:auto-entities"])
        self.assertEqual([c["type"] for c in tree], ["heading", "markdown"])
        self.assertEqual(status[1]["entity"], "sensor.dh_aqara_switch_app_problems")
        self.assertTrue(status[1]["multiline_secondary"])
        self.assertEqual(scan[2]["filter"]["include"], [{"domain": "light"}])
        self.assertEqual(scan[2]["sort"]["method"], "name")
        self.assertNotIn("cards", view)
        self.assertEqual(str(standalone).count("button.dh_aqara_switch_app_scan"), 1)

        cards = {
            "status": status[2],
            "last_action": status[4],
            "scan": scan[1],
            "tree": tree[1],
        }
        source = {
            "status": "dh_aqara_switch_app_card_ru.yaml",
            "last_action": "dh_aqara_switch_app_last_action_ru.yaml",
            "scan": "dh_aqara_switch_app_last_scan_ru.yaml",
            "tree": "dh_aqara_switch_app_tree_ru.yaml",
        }
        for key, filename in source.items():
            with self.subTest(card=key):
                self.assertEqual(cards[key], yaml.safe_load((ROOT / filename).read_text()))

    def test_tree_displays_individual_live_light_state_icons(self):
        tree = yaml.safe_load(
            (ROOT / "dh_aqara_switch_app_tree_ru.yaml").read_text()
        )["content"]
        dashboard = yaml.safe_load(
            (ROOT / "dh_aqara_switch_app_dashboard_ru.yaml").read_text()
        )
        embedded = [
            card["content"]
            for section in dashboard["views"][0]["sections"]
            for card in section["cards"]
            if card["type"] == "markdown"
            and "sensor.dh_aqara_switch_app_devices_details" in card["content"]
        ]
        self.assertEqual(embedded, [tree])
        self.assertIn("{% for target in targets -%}", tree)
        self.assertIn("{% set light_state = states(target) -%}", tree)
        self.assertIn("light_state == 'on'", tree)
        self.assertIn("light_state == 'off'", tree)
        self.assertIn('icon="mdi:lightbulb"', tree)
        self.assertIn('icon="mdi:lightbulb-outline"', tree)
        self.assertIn("color: #f5c542", tree)
        self.assertIn("color: #9299a4", tree)
        self.assertNotIn("mdi:lightbulb-off-outline", tree)
        self.assertIn("❔", tree)
        self.assertIn("недоступен", tree)
        self.assertIn("<pre>", tree)
        self.assertIn("| e }}", tree)
        self.assertNotIn("tojson", tree)
        self.assertNotIn("last_action", tree)
        self.assertNotIn("shadow", tree)

    def test_only_supported_actions_and_no_fake_sensor(self):
        text = (ROOT / "dh_aqara_switch_app_dashboard_ru.yaml").read_text()
        self.assertNotIn("tojson", text)
        self.assertNotIn("button.dh_aqara_switch_app_refresh", text)
        self.assertNotIn("button.dh_aqara_switch_app_check_updates", text)
        self.assertNotIn("light.toggle", text)
        for entity in (
            "sensor.dh_aqara_switch_app_card",
            "sensor.dh_aqara_switch_app_last_action",
            "sensor.dh_aqara_switch_app_devices_details",
            "sensor.dh_aqara_switch_app_scan_details",
            "sensor.dh_aqara_switch_app_problems",
            "button.dh_aqara_switch_app_scan",
        ):
            self.assertIn(entity, text)


if __name__ == "__main__":
    unittest.main()
