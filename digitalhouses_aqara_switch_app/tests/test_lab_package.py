"""Validate virtual light package against intended stable entity ids."""
import unittest
from pathlib import Path
import yaml


class LabPackageTests(unittest.TestCase):
    def test_three_independent_virtual_lights(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "packages" / "dh_aqara_switch_app_lab.yaml"
        content = path.read_text(encoding="utf-8")
        package = yaml.safe_load(content)
        helpers = package["input_boolean"]
        lights = package["template"][0]["light"]
        self.assertEqual(len(lights), 3)
        self.assertEqual(len(helpers), 3)
        self.assertEqual(
            {item["default_entity_id"] for item in lights},
            {"light.dh_aqara_lab_chandelier",
             "light.dh_aqara_lab_spots",
             "light.dh_aqara_lab_led_strip"},
        )
        for light in lights:
            self.assertIn("action", light["turn_on"])
            self.assertIn("action", light["turn_off"])
            self.assertIn("input_boolean.", light["state"])
        self.assertNotIn("tojson", content)
        self.assertNotIn("automation:", content)


if __name__ == "__main__":
    unittest.main()
