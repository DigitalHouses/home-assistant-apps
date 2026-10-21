"""Static safety and structure contract for pilot UI."""
from pathlib import Path
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
LOVE=ROOT/"examples"/"lovelace"


class UIContract(unittest.TestCase):
    def test_all_cards_valid_yaml_and_do_not_use_tojson(self):
        for name in (
            "dh_aqara_switch_app_card_ru.yaml",
            "dh_aqara_switch_app_tree_ru.yaml",
            "dh_aqara_switch_app_last_scan_ru.yaml",
            "dh_aqara_switch_app_problems_ru.yaml",
        ):
            text=(LOVE/name).read_text(encoding="utf-8")
            self.assertNotIn("tojson",text)
            card=yaml.safe_load(text)
            self.assertIsInstance(card,dict,name)
            self.assertIn("type",card,name)

    def test_control_card_uses_real_scan_and_supervisor_restart(self):
        ui=yaml.safe_load((LOVE/"dh_aqara_switch_app_card_ru.yaml").read_text(encoding="utf-8"))
        body=str(ui)
        self.assertIn("button.dh_aqara_switch_app_scan",body)
        self.assertIn("hassio.app_restart",body)
        self.assertIn("confirmation",body)
        self.assertNotIn("button.dh_aqara_switch_app_refresh",body)


if __name__=="__main__":
    unittest.main()
