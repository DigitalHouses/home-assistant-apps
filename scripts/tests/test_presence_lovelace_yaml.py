"""Parse the maintained Presence Lovelace YAML and validate its button-card structure.

Lives in repository-contract tests because PyYAML is installed in that CI job.
The Presence runtime unit test job intentionally does not depend on PyYAML.
"""
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[2] / "digitalhouses_presence_app"
CARD = ROOT / "examples/lovelace/presence_app_card_ru.yaml"
DASH = ROOT / "examples/lovelace/dh_presence_app_dashboard.yaml"
GPS_SOURCES = ROOT / "examples/lovelace/presence_gps_trackers_auto_entities_ru.yaml"
WIFI_SOURCES = ROOT / "examples/lovelace/presence_wifi_trackers_auto_entities_ru.yaml"


class PresenceLovelaceYamlTests(unittest.TestCase):
    def test_portable_auto_entities_use_live_registered_roster_only(self):
        for path, field in ((GPS_SOURCES, "gps_tracker"),
                            (WIFI_SOURCES, "wifi_tracker")):
            with self.subTest(card=path.name):
                text = path.read_text(encoding="utf-8")
                config = yaml.safe_load(text)
                self.assertEqual(config["type"], "custom:auto-entities")
                self.assertEqual(config["card"]["type"], "entities")
                self.assertEqual(config["sort"]["method"], "name")
                self.assertTrue(config["unique"])
                self.assertFalse(config["show_empty"])
                self.assertNotIn("device_tracker.", text)
                self.assertNotIn("tojson", text)
                self.assertEqual(set(config["filter"]), {"template"})
                source = config["filter"]["template"]
                self.assertIn("state_attr('binary_sensor.dh_presence_app_residents_home', 'residents')",
                              source)
                self.assertIn("map(attribute='" + field + "')", source)

    def test_portable_source_templates_work_in_different_homes(self):
        # Execute the actual Lovelace Jinja with a fake HA state_attr.
        env = Environment()
        cases = [
            {
                "alfa": {"gps_tracker": "device_tracker.alfa_ios",
                         "wifi_tracker": "device_tracker.controller_alfa"},
                "bravo": {"gps_tracker": "device_tracker.bravo_android",
                          "wifi_tracker": "device_tracker.router_bravo"},
                "unlinked": {"gps_tracker": "device_tracker.tablet", "wifi_tracker": None},
            },
            {
                "home_one": {"gps_tracker": "device_tracker.somebody_mobile",
                             "wifi_tracker": "device_tracker.ap_67"},
            },
            {},
        ]
        for roster in cases:
            for path, field in ((GPS_SOURCES, "gps_tracker"),
                                (WIFI_SOURCES, "wifi_tracker")):
                with self.subTest(roster=roster, card=path.name):
                    template = yaml.safe_load(path.read_text(encoding="utf-8"))["filter"]["template"]
                    actual = env.from_string(template).render(
                        state_attr=lambda entity, attr: roster).strip()
                    expected = ", ".join(r[field] for r in roster.values()
                                         if r.get(field))
                    self.assertEqual(actual, expected)
                    self.assertNotIn("None", actual)

    def test_yaml_and_styles_icon_js_block(self):
        for path in (CARD, DASH):
            with self.subTest(path=path.name):
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
                if path == CARD:
                    status = document["cards"][0]
                else:
                    status = document["sections"][0]["cards"][1]["cards"][0]
                self.assertEqual(status["type"], "custom:button-card")
                styles = status["styles"]
                icon = styles["icon"]
                self.assertIsInstance(icon, list)
                self.assertEqual(icon[0], {"width": "28px"})
                color = icon[1]["color"]
                self.assertIsInstance(color, str)
                self.assertTrue(color.strip().startswith("[[["), color[:100])
                self.assertTrue(color.strip().endswith("]]]"), color[-100:])
                self.assertIn("update.digitalhouses_presence_app_update", color)
                for key in ("icon", "name", "label"):
                    js = status[key]
                    self.assertIsInstance(js, str)
                    self.assertTrue(js.strip().startswith("[[["))
                    self.assertTrue(js.strip().endswith("]]]"))


if __name__ == "__main__":
    unittest.main()
