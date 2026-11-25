"""Dashboard assembly contract: no copied cards drifting from canonical sources."""
from pathlib import Path
import unittest
import yaml

APP = Path(__file__).resolve().parents[1]
ROOT = APP / "examples" / "lovelace"
CANONICAL_VIEW = APP / "dashboards" / "ru" / "electrica.yaml"


class DashboardTests(unittest.TestCase):
    def test_dh_sync_canonical_view_is_standalone_and_matches_example(self):
        canonical = yaml.safe_load(CANONICAL_VIEW.read_text(encoding="utf-8"))
        example = yaml.safe_load(
            (ROOT / "dh_electrica_app_view_ru.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(canonical, example)
        self.assertEqual(canonical["title"], "electrica")
        self.assertEqual(canonical["path"], "electrica")
        self.assertEqual(canonical["type"], "sections")
        self.assertIsInstance(canonical["sections"], list)
        self.assertNotIn("views", canonical)
        self.assertNotIn("dashboard", canonical)
        self.assertNotIn("DH-Dashboard", CANONICAL_VIEW.read_text(encoding="utf-8"))

    def test_single_view_matches_operator_view_and_pve_layout(self):
        dashboard = yaml.safe_load((ROOT / "dh_electrica_app_dashboard_ru.yaml").read_text())
        standalone = yaml.safe_load((ROOT / "dh_electrica_app_view_ru.yaml").read_text())
        self.assertEqual(dashboard["title"], "DH Electrica")
        self.assertEqual(len(dashboard["views"]), 1)
        self.assertEqual(dashboard["views"][0], standalone)
        view = standalone
        self.assertEqual(view["type"], "sections")
        self.assertEqual(view["max_columns"], 4)
        self.assertEqual(view["path"], "electrica")
        self.assertEqual([s["column_span"] for s in view["sections"]], [1, 3])
        status, tree = [s["cards"] for s in view["sections"]]
        self.assertEqual([c["type"] for c in status], [
            "vertical-stack", "heading", "custom:mushroom-template-card",
            "heading", "markdown"])
        self.assertEqual([c["type"] for c in tree], ["heading", "markdown"])
        self.assertEqual(status[2]["entity"], "sensor.dh_electrica_app_problems")
        self.assertTrue(status[2]["multiline_secondary"])
        self.assertNotIn("cards", view)
        self.assertNotIn("button.dh_electrica_app_scan", str(view))
        self.assertNotIn("custom:auto-entities", str(view))
        cards = {"status":status[0],"last_action":status[4],"tree":tree[1]}
        source = {"status":"dh_electrica_app_card_ru.yaml",
                  "last_action":"dh_electrica_app_last_action_ru.yaml",
                  "tree":"dh_electrica_app_tree_ru.yaml"}
        for key, filename in source.items():
            with self.subTest(card=key):
                self.assertEqual(cards[key], yaml.safe_load((ROOT / filename).read_text()))

    def test_tree_displays_individual_live_light_state_icons(self):
        tree = yaml.safe_load(
            (ROOT / "dh_electrica_app_tree_ru.yaml").read_text()
        )["content"]
        dashboard = yaml.safe_load(
            (ROOT / "dh_electrica_app_dashboard_ru.yaml").read_text()
        )
        embedded = [
            card["content"]
            for section in dashboard["views"][0]["sections"]
            for card in section["cards"]
            if card["type"] == "markdown"
            and "sensor.dh_electrica_app_devices_details" in card["content"]
        ]
        self.assertEqual(embedded, [tree])
        self.assertIn("{% for target in targets -%}", tree)
        self.assertIn("state_attr(entity, 'target_states')", tree)
        self.assertNotIn("states(target)",tree)
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
        text = (ROOT / "dh_electrica_app_dashboard_ru.yaml").read_text()
        self.assertNotIn("tojson", text)
        self.assertIn("button.dh_electrica_app_refresh", text)
        self.assertIn("button.dh_electrica_app_check_updates", text)
        self.assertNotIn("light.toggle", text)
        for entity in (
            "sensor.dh_electrica_app_card",
            "sensor.dh_electrica_app_last_action",
            "sensor.dh_electrica_app_devices_details",
            "sensor.dh_electrica_app_problems",
        ):
            self.assertIn(entity, text)


if __name__ == "__main__":
    unittest.main()
