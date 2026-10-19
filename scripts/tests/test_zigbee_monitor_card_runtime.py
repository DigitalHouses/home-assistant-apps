"""Execute real custom:button-card JS; enforce App-only status responsibility.

Zigbee2MQTT, devices, offline, incidents and releases are separate UI concerns.
Only App card, installed version, latest checked release and Supervisor install
progress may change this status card (plus App management buttons).
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
const performance = {now: () => 12000};
const ctx = {};
function run(code) {
  const source = code.trim();
  if (!source.startsWith('[[[') || !source.endsWith(']]]'))
    throw Error('invalid button-card JS');
  return new Function('states', 'performance', source.slice(3, -3))
    .call(ctx, input.states, performance);
}
const card = input.card;
process.stdout.write(JSON.stringify({
  icon: run(card.icon),
  name: run(card.name),
  label: run(card.label),
  color: run(card.styles.icon[1].color),
}));
"""

APP = "sensor.dh_zigbee_monitor_app_card"
VERSION = "sensor.dh_zigbee_monitor_app_version"
LATEST = "sensor.dh_zigbee_monitor_app_latest_version"
SUPERVISOR = "update.digitalhouses_zigbee_monitor_app_update"


@unittest.skipUnless(shutil.which("node"), "Node.js required for real button-card JS checks")
class ZigbeeCardRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.card_yaml = CARD.read_text(encoding="utf-8")
        standalone = yaml.safe_load(cls.card_yaml)["cards"]
        cls.card = standalone[0]
        cls.chips = standalone[1]["chips"]

    def run_card(self, overrides=None):
        states = {
            APP: {"state": "idle", "attributes": {}},
            VERSION: {"state": "0.1.5"},
            SUPERVISOR: {"state": "off", "attributes": {"in_progress": False}},
        }
        states.update(overrides or {})
        result = subprocess.run(
            ["node", "-e", NODE],
            input=json.dumps({"states": states, "card": self.card}),
            text=True, capture_output=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_idle_is_only_app_status(self):
        shown = self.run_card()
        self.assertEqual(shown["name"], "DH Zigbee Monitor · v0.1.5")
        self.assertEqual(shown["label"], "Приложение запущено")
        self.assertEqual(shown["icon"], "mdi:zigbee")
        self.assertIn("primary-color", shown["color"])

    def test_application_data_and_release_data_never_change_card(self):
        baseline = self.run_card()
        changed = self.run_card({
            "sensor.dh_zigbee_monitor_app_devices": {"state": "130"},
            "sensor.dh_zigbee_monitor_app_offline": {"state": "60"},
            "sensor.dh_zigbee_monitor_app_inventory_details": {
                "state": "ready", "attributes": {"availability_unknown": 24},
            },
            "sensor.dh_zigbee_monitor_app_incidents": {"state": "17"},
            "sensor.dh_zigbee_monitor_app_networks_details": {
                "state": "ready", "attributes": {"networks": [{"status": "offline"}]},
            },
            "sensor.dh_zigbee_monitor_app_latest_version": {"state": "7.0.0"},
            "binary_sensor.dh_zigbee_monitor_app_update_available": {"state": "on"},
        })
        self.assertEqual(changed, baseline)

    def test_only_four_app_related_entities_drive_card(self):
        self.assertEqual(set(self.card["triggers_update"]), {APP, VERSION, LATEST, SUPERVISOR})
        forbidden = (
            "dh_zigbee_monitor_app_devices", "dh_zigbee_monitor_app_offline",
            "dh_zigbee_monitor_app_networks_details",
            "dh_zigbee_monitor_app_inventory_details",
            "dh_zigbee_monitor_app_incidents",
            "dh_zigbee_monitor_app_update_available",
            "Релиз", "Offline", "Supervisor не предлагает",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.card_yaml)

    def test_app_connectivity_loss_is_not_healthy(self):
        shown = self.run_card({APP: {"state": "unavailable"}})
        self.assertEqual(shown["icon"], "mdi:zigbee-off")
        self.assertEqual(shown["label"], "Нет связи с приложением")
        self.assertIn("secondary-text-color", shown["color"])

    def test_app_error_is_preserved(self):
        shown = self.run_card({APP: {"state": "error", "attributes": {
            "error": "Ошибка чтения MQTT",
        }}})
        self.assertEqual(shown["icon"], "mdi:alert-circle")
        self.assertEqual(shown["label"], "Ошибка: Ошибка чтения MQTT")
        self.assertIn("error-color", shown["color"])

    def test_app_refresh_operation_monotonic_clock(self):
        shown = self.run_card({APP: {"state": "running", "attributes": {
            "operation": "refresh", "started_at": "2026-10-19T00:00:00+05:00",
        }}})
        self.assertEqual(shown["icon"], "mdi:progress-clock")
        self.assertEqual(shown["label"], "Обновление данных… 00:00")
        self.assertIn("info-color", shown["color"])

    def test_app_version_check_operation_monotonic_clock(self):
        shown = self.run_card({APP: {"state": "running", "attributes": {
            "operation": "check", "started_at": "2026-10-19T00:00:00+05:00",
        }}})
        self.assertEqual(shown["icon"], "mdi:progress-clock")
        self.assertEqual(shown["label"], "Проверка версии… 00:00")

    def test_refresh_success_measured_duration(self):
        shown = self.run_card({APP: {"state": "success", "attributes": {
            "operation": "refresh", "duration_seconds": 61.4,
        }}})
        self.assertEqual(shown["icon"], "mdi:check-circle")
        self.assertEqual(shown["label"], "Данные обновлены · 1 мин 01 сек")
        self.assertIn("success-color", shown["color"])

    def test_version_check_success_shows_exact_installed_to_latest(self):
        shown = self.run_card({
            APP: {"state": "success", "attributes": {
                "operation": "check", "duration_seconds": 1.2,
            }},
            "binary_sensor.dh_zigbee_monitor_app_update_available": {"state": "on"},
            "sensor.dh_zigbee_monitor_app_latest_version": {"state": "0.1.6"},
        })
        self.assertEqual(shown["label"], "Найдена новая версия: 0.1.5 → 0.1.6")
        self.assertEqual(shown["icon"], "mdi:check-circle")

    def test_supervisor_install_progress_survives_app_disconnect(self):
        shown = self.run_card({
            APP: {"state": "unavailable"},
            SUPERVISOR: {"state": "on", "attributes": {
                "in_progress": True, "update_percentage": 42,
            }},
        })
        self.assertEqual(shown["icon"], "mdi:progress-clock")
        self.assertIn("42% · 00:00", shown["label"])
        self.assertIn("info-color", shown["color"])

    def test_supervisor_update_available_does_not_change_app_status(self):
        baseline = self.run_card()
        shown = self.run_card({SUPERVISOR: {
            "state": "on", "attributes": {"latest_version": "0.1.6",
                                          "in_progress": False},
        }})
        self.assertEqual(shown["name"], baseline["name"])
        self.assertEqual(shown["icon"], baseline["icon"])
        self.assertEqual(shown["color"], baseline["color"])
        self.assertEqual(shown["label"], "Доступно обновление: 0.1.5 → 0.1.6")
        self.assertEqual(self.chips[2]["conditions"], [{
            "entity": SUPERVISOR, "state": "on",
        }])

    def test_installed_version_only_no_downgrade_or_latest_arrows(self):
        shown = self.run_card({
            VERSION: {"state": "0.1.6"},
            "sensor.dh_zigbee_monitor_app_latest_version": {"state": "0.1.5"},
        })
        self.assertEqual(shown["name"], "DH Zigbee Monitor · v0.1.6")
        self.assertNotIn("→", shown["name"])

    def test_action_targets_and_order_match_haos_app_standard(self):
        self.assertEqual([
            c.get("content") or c.get("chip", {}).get("content")
            for c in self.chips
        ], ["Обновить", "Версия", self.chips[2]["chip"]["content"], "Перезапуск"])
        self.assertIn("Обновить {{ installed }} → {{ latest }}",
                      self.chips[2]["chip"]["content"])
        self.assertEqual(self.chips[0]["tap_action"]["target"]["entity_id"],
                         "button.dh_zigbee_monitor_app_refresh")
        self.assertEqual(self.chips[1]["tap_action"]["target"]["entity_id"],
                         "button.dh_zigbee_monitor_app_check_updates")
        self.assertEqual(self.chips[2]["chip"]["tap_action"]["perform_action"],
                         "update.install")
        self.assertEqual(self.chips[2]["chip"]["tap_action"]["data"], {"backup": True})
        self.assertEqual(self.chips[3]["tap_action"]["perform_action"],
                         "hassio.app_restart")


if __name__ == "__main__":
    unittest.main()
