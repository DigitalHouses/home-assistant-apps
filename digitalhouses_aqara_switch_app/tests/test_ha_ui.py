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
            "dh_aqara_switch_app_last_action_ru.yaml",
        ):
            text=(LOVE/name).read_text(encoding="utf-8")
            self.assertNotIn("tojson",text)
            card=yaml.safe_load(text)
            self.assertIsInstance(card,dict,name)
            self.assertIn("type",card,name)

    def test_unified_card_uses_real_runtime_and_supervisor_operations(self):
        card=yaml.safe_load((LOVE/"dh_aqara_switch_app_card_ru.yaml").read_text())
        self.assertEqual(card["type"],"vertical-stack")
        status, chips = card["cards"]
        self.assertEqual(status["type"],"custom:button-card")
        self.assertEqual(status["tap_action"]["action"],"none")
        self.assertEqual(status["entity"],"sensor.dh_aqara_switch_app_card")
        self.assertIn("performance.now()",status["label"])
        self.assertIn("1000",status["update_timer"])
        self.assertIn("sensor.dh_aqara_switch_app_problems",status["triggers_update"])
        self.assertIn("Нет связи",status["label"])
        self.assertIn("in_progress",status["label"])
        self.assertEqual(chips["type"],"custom:mushroom-chips-card")
        scan,version,install,restart=chips["chips"]
        self.assertEqual(scan["tap_action"]["target"]["entity_id"],
                         "button.dh_aqara_switch_app_scan")
        self.assertEqual(version["tap_action"]["action"],"more-info")
        self.assertEqual(install["type"],"conditional")
        self.assertEqual(install["conditions"][0],{
            "entity":"update.digitalhouses_aqara_switch_app_update","state":"on"})
        self.assertEqual(install["chip"]["tap_action"]["perform_action"],"update.install")
        self.assertEqual(install["chip"]["tap_action"]["data"]["backup"],True)
        self.assertEqual(restart["tap_action"]["perform_action"],"hassio.app_restart")
        self.assertEqual(restart["tap_action"]["data"]["app"],
                         "8133339d_digitalhouses_aqara_switch_app")
        for chip in (install["chip"],restart):
            self.assertIn("confirmation",chip["tap_action"])
        self.assertNotIn("button.dh_aqara_switch_app_check_updates",str(card))
        self.assertNotIn("button.dh_aqara_switch_app_refresh",str(card))

    def test_diagnostics_use_real_action_states_and_tree_options(self):
        action=(LOVE/"dh_aqara_switch_app_last_action_ru.yaml").read_text()
        for status in ("sent","partial","skipped","queued","error"):
            self.assertIn("status == '"+status+"'",action)
        self.assertIn("не физическое переключение",action)
        self.assertNotIn("Команда принята Home Assistant.",action)
        tree=(LOVE/"dh_aqara_switch_app_tree_ru.yaml").read_text()
        for keyword in ("bind.target_data.get(target", "settings.rgb_color",
                        "settings.brightness_pct", "settings.transition"):
            self.assertIn(keyword,tree)
        self.assertIn("<pre>",tree)
        self.assertNotIn("tojson",tree)

    def test_control_card_uses_real_scan_and_supervisor_restart(self):
        ui=yaml.safe_load((LOVE/"dh_aqara_switch_app_card_ru.yaml").read_text(encoding="utf-8"))
        body=str(ui)
        self.assertIn("button.dh_aqara_switch_app_scan",body)
        self.assertIn("hassio.app_restart",body)
        self.assertIn("confirmation",body)
        self.assertNotIn("button.dh_aqara_switch_app_refresh",body)


if __name__=="__main__":
    unittest.main()
