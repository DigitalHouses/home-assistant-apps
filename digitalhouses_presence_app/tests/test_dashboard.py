"""DH Presence dashboard uses only genuinely implemented product operations."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "examples/lovelace/presence_app_card_ru.yaml"
DASHBOARD = ROOT / "examples/lovelace/dh_presence_app_dashboard.yaml"


class LovelaceCardTests(unittest.TestCase):
    def test_presence_entities_and_dynamic_resident_roster(self):
        code = CARD.read_text(encoding="utf-8")
        for expected in (
            "binary_sensor.dh_presence_app_residents_home",
            "select.dh_presence_app_mode",
            "sensor.dh_presence_app_version",
            "sensor.dh_presence_app_card",
            "event.dh_presence_app_event",
            "sensor.dh_presence_app_started_at",
            "sensor.dh_presence_app_",
            "attributes?.residents",
            "custom:mushroom-template-card",
            "entity: this.entity_id",
            "binary_sensor.dh_presence_app_*_wifi_home",
            "r.get('user_name')",
            "r.get('status_changed_at')",
            "r.get('gps_changed_at')",
            "r.get('wifi_changed_at')",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, code)

    def test_notification_switches_visible_in_both_cards(self):
        for path in (CARD, DASHBOARD):
            s = path.read_text(encoding="utf-8")
            for key in ("presence", "gps", "wifi"):
                self.assertIn("switch.dh_presence_app_notify_" + key, s)

    def test_real_operations_and_native_supervisor_boundaries(self):
        code = CARD.read_text(encoding="utf-8")
        runtime = (ROOT / "rootfs/app/app.py").read_text(encoding="utf-8")
        for expected in (
            "button.dh_presence_app_refresh",
            "button.dh_presence_app_check_updates",
            "sensor.dh_presence_app_latest_version",
            "update.digitalhouses_presence_app_update",
            "hassio.app_restart",
            "8133339d_digitalhouses_presence_app",
            "update.install",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, code)
        self.assertIn('topic("command")', runtime)
        self.assertIn("fetch_latest_release()", runtime)
        self.assertIn("publish_controls", runtime)
        self.assertIn("action: none", code)
        self.assertIn("type: select-options", code)
        self.assertIn("Последнее подтверждение:", code)
        self.assertIn("По последним GPS-данным:", code)
        self.assertIn("r.get('gps_changed_at')", code)
        self.assertIn("Последние данные проверены", code)

    def test_universal_registry_and_controls_are_visible_without_resident_ids(self):
        code = CARD.read_text(encoding="utf-8")
        for item in (
            "custom:auto-entities",
            'entity_id: "*dh_presence_app_*"',
            "entity_id: update.digitalhouses_presence_app_update",
            "method: entity_id",
            "button.dh_presence_app_refresh",
            "button.dh_presence_app_check_updates",
            "select.dh_presence_app_mode",
            "sensor.dh_presence_app_last_refresh",
            "Refresh не выполнялся",
        ):
            with self.subTest(item=item):
                self.assertIn(item, code)
        # The dynamically discovered resident ID is not a hardcoded key.
        self.assertNotIn("39fb60fca44a2aa6", code)
        self.assertEqual(code.count("custom:auto-entities"), 2)

    def test_dynamic_mushroom_roster_has_names_states_and_transition_times(self):
        card = CARD.read_text(encoding="utf-8")
        self.assertIn('entity_id: "binary_sensor.dh_presence_app_*_wifi_home"', card)
        self.assertIn("entity: this.entity_id", card)
        self.assertIn("custom:mushroom-template-card", card)
        self.assertIn("multiline_secondary: true", card)
        self.assertIn("r.get('user_name')", card)
        self.assertIn("r.get('name')", card)
        self.assertIn("Имя не задано", card)
        for attr in ("status_changed_at", "gps_changed_at", "wifi_changed_at"):
            self.assertIn(attr, card)
        self.assertIn("Не обнаружен (ARP)", card)
        self.assertIn("Hybrid · GPS + Wi-Fi", card)
        self.assertNotIn("Hybrid: пока только GPS", card)
        self.assertNotIn("39fb60fca44a2aa6", card)
        self.assertNotIn("roster | dictsort", card)

    def test_single_install_ingress_without_custom_registration_resources(self):
        card = CARD.read_text(encoding="utf-8")
        config = (ROOT / "config.yaml").read_text(encoding="utf-8")
        ui = (ROOT / "rootfs/app/dh_presence/ui.py").read_text(encoding="utf-8")
        self.assertNotIn("custom:dh-presence-register-card", card)
        self.assertIn("ingress: true", config)
        self.assertIn("ingress_port: 8099", config)
        self.assertIn("X-Remote-User-Id", ui)
        self.assertIn("X-Remote-User-Display-Name", ui)
        self.assertIn("api/register", ui)
        self.assertIn("start_ingress_ui", ui)
        self.assertFalse((ROOT / "registration_bridge").exists())

    def test_phone_registration_launcher_is_safe_and_single_install(self):
        card = CARD.read_text(encoding="utf-8")
        launcher = (ROOT / "examples/lovelace/presence_registration_card_ru.yaml").read_text(encoding="utf-8")
        config = (ROOT / "config.yaml").read_text(encoding="utf-8")
        self.assertIn("ingress: true", config)
        self.assertIn("registration_ready", launcher)
        self.assertIn("version[2] >= 11", launcher)
        self.assertIn("variables.registration_ready ? 'navigate' : 'none'", launcher)
        self.assertIn("/app/8133339d_digitalhouses_presence_app", launcher)
        self.assertNotIn("/hassio/ingress/", launcher)
        self.assertNotIn("/hassio/ingress/", card)
        self.assertIn("Пока недоступно", launcher)
        self.assertIn("Регистрация телефона", launcher)
        self.assertIn("type: custom:button-card", launcher)
        self.assertNotIn("custom:dh-presence-register-card", card)
        self.assertEqual(card.count("name: Регистрация телефона"), 1)
        # The same launcher is embedded in the maintained card, not duplicated
        # as a separate public system or custom frontend resource.
        noncomment = [line for line in launcher.splitlines()
                      if line.strip() and not line.startswith("#")]
        embedded = "  - " + noncomment[0] + "\n" + "\n".join(
            "    " + line for line in noncomment[1:])
        self.assertIn(embedded, "\n".join(
            line for line in card.splitlines() if line.strip()))

    def test_admin_diagnostics_card_remains_frontend_admin_only(self):
        card = CARD.read_text(encoding="utf-8")
        launch = (ROOT / "examples/lovelace/presence_admin_debug_card_ru.yaml").read_text(encoding="utf-8")
        self.assertIn("hidden:", launch)
        self.assertIn("hass.user?.is_admin !== true", launch)
        self.assertIn("Диагностика регистрации", card)

    def test_auto_entities_uses_native_filter_not_generated_json(self):
        # The CI Presence runner deliberately has no PyYAML dependency; the
        # standalone YAML is checked for structure independently of it.
        standalone = ROOT / "examples/lovelace/presence_residents_auto_entities_ru.yaml"
        source = standalone.read_text(encoding="utf-8")
        self.assertTrue(source.startswith("type: custom:auto-entities\n"))
        for required in (
            "card_param: cards",
            "  include:",
            'entity_id: "binary_sensor.dh_presence_app_*_wifi_home"',
            "type: custom:mushroom-template-card",
            "entity: this.entity_id",
            "multiline_secondary: true",
            "status_changed_at",
            "gps_changed_at",
            "wifi_changed_at",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)
        self.assertNotIn("  template: |", source)
        self.assertNotIn("roster | dictsort", source)
        for file in (CARD, DASHBOARD):
            content = file.read_text(encoding="utf-8")
            self.assertIn('entity_id: "binary_sensor.dh_presence_app_*_wifi_home"', content)
            self.assertIn("entity: this.entity_id", content)
            self.assertNotIn("roster | dictsort", content)

    def test_dashboard_embeds_same_card_without_drift(self):
        card = CARD.read_text(encoding="utf-8")
        dashboard = DASHBOARD.read_text(encoding="utf-8")
        lines = [line for line in card.splitlines()
                 if line.strip() and not line.startswith("#")]
        expected = "      - " + lines[0] + "\n" + "\n".join("        " + line for line in lines[1:])
        actual = "\n".join(line for line in dashboard.splitlines() if line.strip())
        self.assertIn(expected, actual)


if __name__ == "__main__":
    unittest.main()
