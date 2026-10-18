"""Parse the maintained Presence Lovelace YAML and validate its button-card structure.

Lives in repository-contract tests because PyYAML is installed in that CI job.
The Presence runtime unit test job intentionally does not depend on PyYAML.
"""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2] / "digitalhouses_presence_app"
CARD = ROOT / "examples/lovelace/presence_app_card_ru.yaml"
DASH = ROOT / "examples/lovelace/dh_presence_app_dashboard.yaml"


class PresenceLovelaceYamlTests(unittest.TestCase):
    def test_yaml_and_styles_icon_js_block(self):
        for path in (CARD, DASH):
            with self.subTest(path=path.name):
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
                if path == CARD:
                    status = document["cards"][0]
                else:
                    status = document["sections"][0]["cards"][0]["cards"][0]
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
