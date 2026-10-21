"""Validate six independent virtual Aqara LAB lights and stable prior IDs."""
import unittest
from pathlib import Path
import yaml


class LabPackageTests(unittest.TestCase):
    def test_six_independent_virtual_lights(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "examples" / "packages" / "dh_aqara_switch_app_lab.yaml"
        content = path.read_text(encoding="utf-8")
        package = yaml.safe_load(content)
        self.assertEqual(set(package), {"input_boolean", "template"})
        helpers = package["input_boolean"]
        template = package["template"]
        self.assertEqual(len(template), 1)
        lights = template[0]["light"]
        self.assertEqual(len(lights), 6)
        self.assertEqual(len(helpers), 6)

        expected = {
            "chandelier", "spots", "led_strip",
            "sconce", "floor_lamp", "night_light",
        }
        self.assertEqual(set(helpers), {"dh_aqara_lab_" + key for key in expected})
        self.assertEqual({item["default_entity_id"] for item in lights},
                         {"light.dh_aqara_lab_" + key for key in expected})
        self.assertEqual({item["unique_id"] for item in lights},
                         {"dh_aqara_lab_" + key for key in expected})

        for light in lights:
            helper = "input_boolean." + light["unique_id"]
            self.assertIn(helper, light["state"])
            self.assertEqual(light["turn_on"]["action"], "input_boolean.turn_on")
            self.assertEqual(light["turn_off"]["action"], "input_boolean.turn_off")
            self.assertEqual(light["turn_on"]["target"]["entity_id"], helper)
            self.assertEqual(light["turn_off"]["target"]["entity_id"], helper)
            self.assertNotIn("initial", helpers[light["unique_id"]])

        self.assertNotIn("tojson", content)
        self.assertNotIn("automation:", content)
        self.assertNotIn("mqtt:", content)

    def test_lovelace_lists_all_six_lights(self):
        root = Path(__file__).resolve().parents[1] / "examples" / "lovelace"
        card = yaml.safe_load((root / "dh_aqara_switch_app_lab_lights_ru.yaml")
                              .read_text(encoding="utf-8"))
        self.assertEqual(card["type"], "entities")
        entries = card["entities"]
        self.assertEqual(len(entries), 6)
        self.assertEqual({entry["entity"] for entry in entries}, {
            "light.dh_aqara_lab_chandelier",
            "light.dh_aqara_lab_spots",
            "light.dh_aqara_lab_led_strip",
            "light.dh_aqara_lab_sconce",
            "light.dh_aqara_lab_floor_lamp",
            "light.dh_aqara_lab_night_light",
        })

    def test_sections_grid_for_six_light_lab(self):
        root = Path(__file__).resolve().parents[1] / "examples" / "lovelace"
        card = yaml.safe_load((root / "dh_aqara_switch_app_lab_section_ru.yaml")
                              .read_text(encoding="utf-8"))
        self.assertEqual(card["type"], "grid")
        self.assertEqual(card["column_span"], 4)
        self.assertEqual(len([c for c in card["cards"] if c["type"] == "tile"]), 6)


if __name__ == "__main__":
    unittest.main()
