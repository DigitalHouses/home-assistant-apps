"""Validate the UI-first/Recorder contract before Zigbee Monitor is installable."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "digitalhouses_zigbee_monitor_app"
DASHBOARD = APP / "examples/lovelace/dh_zigbee_monitor_app_dashboard.yaml"
RECORDER = APP / "examples/packages/dh_zigbee_monitor_app_global_package.yaml"

HISTORICAL = {
    "sensor.dh_zigbee_monitor_app_networks",
    "sensor.dh_zigbee_monitor_app_devices",
    "sensor.dh_zigbee_monitor_app_offline",
    "sensor.dh_zigbee_monitor_app_spammers",
    "sensor.dh_zigbee_monitor_app_incidents",
    "sensor.dh_zigbee_monitor_app_messages_rate_5m",
}
DETAILS = {
    "sensor.dh_zigbee_monitor_app_networks_details",
    "sensor.dh_zigbee_monitor_app_offline_details",
    "sensor.dh_zigbee_monitor_app_top_1h_details",
    "sensor.dh_zigbee_monitor_app_top_24h_details",
    "sensor.dh_zigbee_monitor_app_top_7d_details",
    "sensor.dh_zigbee_monitor_app_incidents_details",
}


class ZigbeeMonitorUiDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_dashboard = DASHBOARD.read_text(encoding="utf-8")
        cls.dashboard = yaml.safe_load(cls.raw_dashboard)
        cls.raw_recorder = RECORDER.read_text(encoding="utf-8")
        cls.package = yaml.safe_load(cls.raw_recorder)
        cls.recorder = cls.package["dh_zigbee_monitor_app_global_package"]["recorder"]

    def test_dashboard_is_sections_with_a_title(self):
        self.assertEqual(self.dashboard["type"], "sections")
        self.assertEqual(self.dashboard["max_columns"], 4)
        cards = [card for sec in self.dashboard["sections"] for card in sec["cards"]]
        self.assertTrue(any(card.get("type") == "heading" and
                            card.get("heading") == "Zigbee Monitor" for card in cards))
        self.assertIn("sensor.dh_zigbee_monitor_app_card", self.raw_dashboard)

    def test_standard_app_card_has_four_real_actions(self):
        cards = [card for sec in self.dashboard["sections"] for card in sec["cards"]]
        stacks = [card for card in cards if card.get("type") == "vertical-stack"]
        self.assertEqual(len(stacks), 1)
        status, chips = stacks[0]["cards"]
        self.assertEqual(status["entity"], "sensor.dh_zigbee_monitor_app_card")
        self.assertEqual(chips["type"], "custom:mushroom-chips-card")
        self.assertEqual(
            [c.get("content") or c.get("chip", {}).get("content") for c in chips["chips"]],
            ["Обновить", "Версия", "Новая версия", "Перезапуск"],
        )
        self.assertEqual(chips["chips"][0]["tap_action"]["target"]["entity_id"],
                         "button.dh_zigbee_monitor_app_refresh")
        self.assertEqual(chips["chips"][1]["tap_action"]["target"]["entity_id"],
                         "button.dh_zigbee_monitor_app_check_updates")
        self.assertEqual(chips["chips"][2]["chip"]["tap_action"]["perform_action"],
                         "update.install")
        self.assertEqual(chips["chips"][3]["tap_action"]["perform_action"],
                         "hassio.app_restart")
        self.assertEqual(status["tap_action"]["action"], "none")

    def test_every_detail_sensor_is_explicitly_excluded(self):
        used = set(re.findall(r"state_attr\('([^']+)'", self.raw_dashboard))
        self.assertEqual(used, DETAILS)
        excluded = set(self.recorder["exclude"]["entities"])
        self.assertTrue(DETAILS.issubset(excluded))
        self.assertIn("sensor.dh_zigbee_monitor_app_*_details",
                      self.recorder["exclude"]["entity_globs"])
        self.assertIn("event.dh_zigbee_monitor_app_event", excluded)
        self.assertIn("sensor.dh_zigbee_monitor_app_card", excluded)

    def test_recorder_include_only_scalars(self):
        self.assertEqual(set(self.recorder["include"]["entities"]), HISTORICAL)
        self.assertFalse(HISTORICAL & set(self.recorder["exclude"]["entities"]))
        self.assertFalse(any(s.endswith("_details") for s in HISTORICAL))
        self.assertFalse(any("event." in s for s in HISTORICAL))

    def test_dashboard_is_presentation_only(self):
        forbidden = (
            "tojson", "integration_entities(", "device_id(", "unique_id(",
            "groupby(", "selectattr(", "expand(", "sum(", "average(",
        )
        for expression in forbidden:
            self.assertNotIn(expression, self.raw_dashboard)
        self.assertNotIn("tojson", self.raw_recorder)
        for item in DETAILS:
            self.assertIn("states('" + item + "') in ['unknown', 'unavailable']",
                          self.raw_dashboard)

    def test_it_is_not_falsely_marked_installable(self):
        self.assertFalse((APP / "digitalhouses.app").exists())
        self.assertFalse((APP / "config.yaml").exists())


if __name__ == "__main__":
    unittest.main()
