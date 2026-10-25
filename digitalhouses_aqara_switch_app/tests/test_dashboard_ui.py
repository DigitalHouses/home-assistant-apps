"""Dashboard assembly contract: no copied cards drifting from canonical sources."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1] / "examples" / "lovelace"


class DashboardTests(unittest.TestCase):
    def test_single_view_with_canonical_cards(self):
        dashboard = yaml.safe_load((ROOT / "dh_aqara_switch_app_dashboard_ru.yaml").read_text())
        self.assertEqual(dashboard["title"], "DH Aqara Switch")
        self.assertEqual(len(dashboard["views"]), 1)
        view = dashboard["views"][0]
        self.assertEqual(view["type"], "sections")
        self.assertEqual(view["max_columns"], 2)
        sections = view["sections"]
        self.assertEqual(len(sections), 3)
        self.assertEqual([s["column_span"] for s in sections], [1, 1, 2])
        cards = [[c for c in s["cards"] if c["type"] != "heading"] for s in sections]
        source = {
            "status": "dh_aqara_switch_app_card_ru.yaml",
            "last_action": "dh_aqara_switch_app_last_action_ru.yaml",
            "scan": "dh_aqara_switch_app_last_scan_ru.yaml",
            "problems": "dh_aqara_switch_app_problems_ru.yaml",
            "tree": "dh_aqara_switch_app_tree_ru.yaml",
        }
        actual = {
            "status": cards[0][0],
            "last_action": cards[0][1],
            "scan": cards[1][0],
            "problems": cards[1][1],
            "tree": cards[2][0],
        }
        for key, filename in source.items():
            with self.subTest(card=key):
                self.assertEqual(actual[key], yaml.safe_load((ROOT / filename).read_text()))

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
