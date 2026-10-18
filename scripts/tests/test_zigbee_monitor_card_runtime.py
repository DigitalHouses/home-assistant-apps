"""Execute actual custom:button-card JavaScript against representative HA states.

The existing YAML shape checks do not catch incorrect product-status priorities,
a stale newer-version arrow, or confusion between a published GitHub release
and a Supervisor-installable HAOS App update.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CARD = ROOT / "digitalhouses_zigbee_monitor_app/examples/lovelace/dh_zigbee_monitor_app_card_ru.yaml"

NODE = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const perf = {now: () => 12000};
const ctx = {};
function evaluate(template) {
  const raw = template.trim();
  if (!raw.startsWith('[[[') || !raw.endsWith(']]]'))
    throw Error('invalid button-card template');
  return new Function('states', 'performance', raw.slice(3, -3))
    .call(ctx, input.states, perf);
}
const card = input.card;
const output = {
  icon: evaluate(card.icon),
  name: evaluate(card.name),
  label: evaluate(card.label),
  color: evaluate(card.styles.icon[1].color)
};
process.stdout.write(JSON.stringify(output));
"""

CARD_ENTITY = "sensor.dh_zigbee_monitor_app_card"
SUPERVISOR = "update.digitalhouses_zigbee_monitor_app_update"
VERSION = "sensor.dh_zigbee_monitor_app_version"
LATEST = "sensor.dh_zigbee_monitor_app_latest_version"
UPDATE_AVAILABLE = "binary_sensor.dh_zigbee_monitor_app_update_available"
INVENTORY = "sensor.dh_zigbee_monitor_app_inventory_details"
NETWORKS = "sensor.dh_zigbee_monitor_app_networks_details"
DEVICES = "sensor.dh_zigbee_monitor_app_devices"
OFFLINE = "sensor.dh_zigbee_monitor_app_offline"


@unittest.skipUnless(shutil.which("node"), "Node.js needed to execute button-card JavaScript")
class ZigbeeCardRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.card = yaml.safe_load(CARD.read_text(encoding="utf-8"))["cards"][0]
        cls.chips = yaml.safe_load(CARD.read_text(encoding="utf-8"))["cards"][1]["chips"]

    def run_card(self, overrides=None):
        states = {
            CARD_ENTITY: {"state": "idle", "attributes": {}},
            VERSION: {"state": "0.1.5"},
            LATEST: {"state": "0.1.6"},
            UPDATE_AVAILABLE: {"state": "on"},
            INVENTORY: {"state": "ready", "attributes": {"availability_unknown": 2}},
            NETWORKS: {"state": "ready", "attributes": {
                "networks": [{"network_id": "site_1", "status": "online"}]
            }},
            DEVICES: {"state": "6"},
            OFFLINE: {"state": "unavailable"},
            SUPERVISOR: {"state": "off", "attributes": {
                "latest_version": "0.1.5", "in_progress": False
            }},
        }
        states.update(overrides or {})
        result = subprocess.run(
            ["node", "-e", NODE], input=json.dumps({
                "states": states, "card": self.card,
            }), text=True, capture_output=True, check=False, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_published_release_with_supervisor_off_does_not_claim_installation(self):
        shown = self.run_card()
        self.assertIn("v0.1.5 → v0.1.6", shown["name"])
        self.assertIn("Supervisor не предлагает установку", shown["label"])
        self.assertNotIn("Можно установить", shown["label"])
        self.assertIn("warning-color", shown["color"])
        self.assertNotEqual(shown["icon"], "mdi:check-circle")
        self.assertEqual(self.chips[2]["conditions"], [
            {"entity": SUPERVISOR, "state": "on"},
        ])
        self.assertEqual(self.chips[2]["chip"]["tap_action"]["perform_action"],
                         "update.install")

    def test_version_check_success_with_new_release_is_not_green_healthy(self):
        shown = self.run_card({
            CARD_ENTITY: {"state": "success", "attributes": {
                "operation": "check", "duration_seconds": 1.2,
            }}
        })
        self.assertIn("Релиз найден", shown["label"])
        self.assertIn("1 сек", shown["label"])
        self.assertIn("Supervisor пока не предлагает установку", shown["label"])
        self.assertNotEqual(shown["icon"], "mdi:check-circle")
        self.assertIn("warning-color", shown["color"])

    def test_supervisor_installable_is_independent_of_app_release_flag(self):
        shown = self.run_card({
            UPDATE_AVAILABLE: {"state": "off"},
            SUPERVISOR: {"state": "on", "attributes": {
                "latest_version": "0.1.6", "in_progress": False,
            }},
        })
        self.assertIn("v0.1.5 → v0.1.6", shown["name"])
        self.assertIn("Можно установить обновление", shown["label"])
        self.assertEqual(self.chips[2]["chip"]["tap_action"]["target"]["entity_id"],
                         SUPERVISOR)
        self.assertEqual(self.chips[2]["chip"]["tap_action"]["data"], {"backup": True})

    def test_installer_progress_survives_app_disconnect(self):
        shown = self.run_card({
            CARD_ENTITY: {"state": "unavailable"},
            SUPERVISOR: {"state": "on", "attributes": {
                "latest_version": "0.1.6", "in_progress": True,
                "update_percentage": 42,
            }},
        })
        self.assertEqual(shown["icon"], "mdi:progress-clock")
        self.assertIn("42% · 00:00", shown["label"])
        self.assertIn("info-color", shown["color"])

    def test_error_must_win_over_update_availability(self):
        shown = self.run_card({
            CARD_ENTITY: {"state": "error", "attributes": {"error": "MQTT недоступен"}},
        })
        self.assertEqual(shown["icon"], "mdi:alert-circle")
        self.assertIn("MQTT недоступен", shown["label"])
        self.assertIn("error-color", shown["color"])

    def test_network_failure_must_win_over_update_or_success(self):
        shown = self.run_card({
            NETWORKS: {"state": "ready", "attributes": {
                "networks": [{"network_id": "site_1", "status": "offline"}],
            }},
            CARD_ENTITY: {"state": "success", "attributes": {
                "operation": "check", "duration_seconds": 2,
            }},
        })
        self.assertEqual(shown["icon"], "mdi:lan-disconnect")
        self.assertIn("error-color", shown["color"])
        # Success status remains an operation result, not a false network recovery.
        self.assertIn("Релиз найден", shown["label"])

    def test_stale_release_flag_cannot_show_downgrade(self):
        shown = self.run_card({
            VERSION: {"state": "0.1.6"},
            LATEST: {"state": "0.1.5"},
        })
        self.assertNotIn("→", shown["name"])
        self.assertNotIn("Релиз опубликован", shown["label"])

    def test_healthy_idle_and_stable_version_do_not_warn(self):
        shown = self.run_card({
            VERSION: {"state": "0.1.6"},
            LATEST: {"state": "0.1.6"},
            UPDATE_AVAILABLE: {"state": "off"},
            INVENTORY: {"state": "ready", "attributes": {"availability_unknown": 0}},
            OFFLINE: {"state": "0"},
        })
        self.assertEqual(shown["icon"], "mdi:zigbee")
        self.assertEqual(shown["name"], "DH Zigbee Monitor · v0.1.6")
        self.assertEqual(shown["label"], "6 устройств · Offline: 0")

    def test_running_check_shows_monotonic_ui_timer(self):
        shown = self.run_card({
            CARD_ENTITY: {"state": "running", "attributes": {
                "operation": "check", "started_at": "2026-10-19T00:00:00+05:00",
            }},
        })
        self.assertEqual(shown["icon"], "mdi:progress-clock")
        self.assertIn("00:00", shown["label"])
        self.assertIn("info-color", shown["color"])

    def test_missing_app_does_not_look_healthy(self):
        shown = self.run_card({
            CARD_ENTITY: {"state": "unavailable"},
        })
        self.assertEqual(shown["icon"], "mdi:zigbee-off")
        self.assertEqual(shown["label"], "Нет связи с приложением")
        self.assertIn("secondary-text-color", shown["color"])

    def test_action_targets_and_order_match_reference_haos_apps(self):
        self.assertEqual([
            c.get("content") or c.get("chip", {}).get("content")
            for c in self.chips
        ], ["Обновить", "Версия", "Новая версия", "Перезапуск"])
        self.assertEqual(
            self.chips[0]["tap_action"]["target"]["entity_id"],
            "button.dh_zigbee_monitor_app_refresh",
        )
        self.assertEqual(
            self.chips[1]["tap_action"]["target"]["entity_id"],
            "button.dh_zigbee_monitor_app_check_updates",
        )
        self.assertEqual(self.chips[3]["tap_action"]["perform_action"],
                         "hassio.app_restart")


if __name__ == "__main__":
    unittest.main()
