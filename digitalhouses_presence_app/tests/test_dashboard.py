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
            "_distance",
            "_gps_home",
            "_wifi_home",
            "attributes?.residents",
            "resident.user_name",
            "shownName",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, code)

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
        self.assertIn("resident.gps_reported_at", code)
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
        self.assertEqual(code.count("custom:auto-entities"), 1)

    def test_resident_name_precedes_device_and_missing_names_are_explicit(self):
        card = CARD.read_text(encoding="utf-8")
        self.assertIn("residentLabel(a[1]).localeCompare(residentLabel(b[1]), 'ru')", card)
        self.assertIn("typeof resident.user_name === 'string'", card)
        self.assertIn("resident.user_name.trim()", card)
        self.assertIn("const shownName = (personName || 'Имя не задано')", card)
        self.assertIn("+ ' (' + deviceName + ')'", card)
        # Friendly phone labels are never used as invented human names.
        self.assertNotIn("(personName || deviceName)", card)

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
