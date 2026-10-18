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
        self.assertEqual(chips["chips"][2]["conditions"], [{
            "entity": "update.digitalhouses_zigbee_monitor_app_update",
            "state": "on",
        }])
        install = chips["chips"][2]["chip"]["tap_action"]
        self.assertEqual(install["action"], "perform-action")
        self.assertEqual(install["perform_action"], "update.install")
        self.assertEqual(install["target"]["entity_id"],
                         "update.digitalhouses_zigbee_monitor_app_update")
        self.assertEqual(install["data"], {"backup": True})
        self.assertIn("резервную копию", install["confirmation"]["text"])
        self.assertNotIn("navigation_path", install)
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

    def test_canonical_card_equals_embedded_dashboard_card(self):
        source = APP / "examples/lovelace/dh_zigbee_monitor_app_card_ru.yaml"
        standalone = yaml.safe_load(source.read_text(encoding="utf-8"))
        self.assertEqual(standalone["type"], "vertical-stack")
        self.assertEqual(standalone["grid_options"]["columns"], 12)
        embedded = next(
            c for section in self.dashboard["sections"] for c in section["cards"]
            if c.get("type") == "vertical-stack"
        )
        self.assertEqual(standalone["cards"], embedded["cards"])
        actions = standalone["cards"][1]["chips"]
        self.assertEqual(
            [a.get("content") or a.get("chip", {}).get("content") for a in actions],
            ["Обновить", "Версия", "Новая версия", "Перезапуск"],
        )
        self.assertEqual(actions[2]["conditions"][0]["entity"],
                         "update.digitalhouses_zigbee_monitor_app_update")
        self.assertEqual(actions[2]["conditions"][0]["state"], "on")
        self.assertEqual(actions[2]["chip"]["tap_action"]["perform_action"], "update.install")
        self.assertEqual(actions[2]["chip"]["tap_action"]["target"]["entity_id"],
                         "update.digitalhouses_zigbee_monitor_app_update")
        self.assertTrue(actions[2]["chip"]["tap_action"]["data"]["backup"])
        self.assertNotIn("navigation_path", actions[2]["chip"]["tap_action"])
        self.assertEqual(actions[3]["tap_action"]["perform_action"], "hassio.app_restart")
        self.assertEqual(actions[3]["tap_action"]["data"]["app"],
                         "8133339d_digitalhouses_zigbee_monitor_app")

    def test_verified_supervisor_update_drives_install_chip(self):
        source = APP / "examples/lovelace/dh_zigbee_monitor_app_card_ru.yaml"
        standalone = yaml.safe_load(source.read_text(encoding="utf-8"))
        chip = standalone["cards"][1]["chips"][2]
        self.assertEqual(chip["conditions"][0]["entity"],
                         "update.digitalhouses_zigbee_monitor_app_update")
        self.assertEqual(chip["conditions"][0]["state"], "on")
        action = chip["chip"]["tap_action"]
        self.assertEqual(action["action"], "perform-action")
        self.assertEqual(action["perform_action"], "update.install")
        self.assertEqual(action["target"]["entity_id"],
                         "update.digitalhouses_zigbee_monitor_app_update")
        self.assertTrue(action["data"]["backup"])
        self.assertIn("Установить", action["confirmation"]["text"])
        self.assertNotIn("navigation_path", action)

    def test_elapsed_and_result_duration_are_whole_seconds(self):
        source = APP / "examples/lovelace/dh_zigbee_monitor_app_card_ru.yaml"
        content = source.read_text(encoding="utf-8")
        for yaml_text in (content, self.raw_dashboard):
            self.assertIn("Math.floor((performance.now() - start) / 1000)", yaml_text)
            self.assertIn("Math.round(Math.max(0, t))", yaml_text)
            self.assertNotIn("t.toFixed(1)", yaml_text)

    def test_all_dynamic_tables_use_html_not_fragile_markdown_pipes(self):
        # Home Assistant renders Markdown-card Jinja before Marked.js.
        # Jinja removes newlines around for/if tags; Markdown pipe tables then
        # collapse into plain text, as seen in the 4-column HAOS dashboard.
        # HTML tr/td structure is independent of output newlines.
        cards = [card for sec in self.dashboard["sections"]
                 for card in sec["cards"]
                 if card.get("type") == "markdown"]
        templated_tables = [card["content"] for card in cards
                            if "<table>" in card["content"]]
        self.assertEqual(len(templated_tables), 7)
        for content in templated_tables:
            with self.subTest(table=content[:60]):
                self.assertEqual(content.count("<table>"), 1)
                self.assertEqual(content.count("</table>"), 1)
                self.assertEqual(content.count("<thead>"), 1)
                self.assertEqual(content.count("<tbody>"), 1)
                self.assertEqual(content.count("</tbody>"), 1)
                self.assertIn("<tr>", content)
                self.assertIn("</tr>", content)
                self.assertIn("<td>", content)
                self.assertIn("</td>", content)
                self.assertIn("{% for ", content)
                self.assertNotRegex(content, r"(?m)^\s*\|")
        self.assertIn("item.power_label", self.raw_dashboard)
        self.assertIn("item.last_mqtt_message_at[5:16]", self.raw_dashboard)
        self.assertIn("availability_reason_label", self.raw_dashboard)
        self.assertNotIn("tojson", self.raw_dashboard)

    def test_power_and_mqtt_activity_are_only_inventory_attributes(self):
        self.assertIn("item.power_label", self.raw_dashboard)
        self.assertIn("item.last_mqtt_message_at", self.raw_dashboard)
        self.assertIn("Последний MQTT", self.raw_dashboard)
        self.assertIn("sensor.dh_zigbee_monitor_app_inventory_details",
                      self.recorder["exclude"]["entities"])
        self.assertEqual(
            set(self.recorder["include"]["entities"]), HISTORICAL,
        )

    def test_inventory_diagnostics_are_ui_only(self):
        self.assertIn("availability_reason_label", self.raw_dashboard)
        self.assertIn("availability_unknown", self.raw_dashboard)
        self.assertIn("sensor.dh_zigbee_monitor_app_refresh_state",
                      self.recorder["exclude"]["entities"])
        self.assertNotIn("sensor.dh_zigbee_monitor_app_refresh_state",
                         self.recorder["include"]["entities"])

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

    def test_app_is_installable_only_with_canonical_metadata(self):
        self.assertEqual((APP / "digitalhouses.app").read_text().strip(), "type = haos_addon")
        config = yaml.safe_load((APP / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(config["slug"], "digitalhouses_zigbee_monitor_app")
        self.assertEqual(config["version"], "0.1.6"
        self.assertEqual(config["stage"], "experimental")


if __name__ == "__main__":
    unittest.main()
