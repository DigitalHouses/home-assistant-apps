"""Regression tests: local notification example is native, non-duplicating, safe."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "examples/packages/dh_presence_app_notification_local_package_ru.yaml"
CORE = ROOT / "rootfs/app/dh_presence/core.py"
RUNTIME = ROOT / "rootfs/app/app.py"


class NotificationPackageTests(unittest.TestCase):
    def test_native_package_root(self):
        content = PACKAGE.read_text(encoding="utf-8")
        self.assertIn("\nautomation:\n", content)
        self.assertNotIn("\ndh_presence_app_notification_local_package:\n", content)

    def test_merge_named_local_package_matches_canonical_notifications(self):
        keyed = (ROOT / "examples/packages/dh_presence_app_notification_merge_named_ru.yaml").read_text(
            encoding="utf-8")
        canonical = PACKAGE.read_text(encoding="utf-8")
        self.assertIn("dh_presence_app_notification:\n  automation:", keyed)
        self.assertEqual(keyed.count("- action: script.write2log"), 7)
        self.assertEqual(keyed.count('title: "'), 7)
        self.assertNotIn("  recorder:", keyed)
        source = canonical[canonical.index("automation:\n"):]
        expected = "\n".join("  " + line if line else "" for line in source.split("\n"))
        self.assertIn("dh_presence_app_notification:\n" + expected, keyed)

    def test_package_seeds_english_entity_id_with_russian_ui_name(self):
        """Both packages must create a canonical English automation entity ID.

        The deliberately new YAML unique id is the one-time migration away
        from the old transliterated entity registry identity on existing homes.
        """
        standalone = PACKAGE.read_text(encoding="utf-8")
        merged = (ROOT / "examples/packages/dh_presence_app_notification_merge_named_ru.yaml").read_text(
            encoding="utf-8")
        for name, code in (("standalone", standalone), ("merge_named", merged)):
            with self.subTest(package=name):
                self.assertEqual(code.count("- id: dh_presence_notifications"), 1)
                self.assertEqual(code.count('alias: "DH Presence Notifications"'), 1)
                self.assertEqual(code.count("automation.dh_presence_notifications:"), 1)
                self.assertEqual(code.count('friendly_name: "DH Presence · Уведомления"'), 1)
                self.assertNotIn("id: dh_presence_app_notifications", code)
                self.assertNotIn("alias: \"DH Presence · Уведомления\"", code)
                self.assertNotIn("automation.dh_presence_uvedomleniia:", code)
                self.assertEqual(code.count("- action: script.write2log"), 7)
                self.assertIn("id: zone_enter", code)
                self.assertIn("id: zone_leave", code)
        self.assertIn("\nhomeassistant:\n  customize:\n    automation.dh_presence_notifications:\n",
                      standalone)
        self.assertIn("\n  homeassistant:\n    customize:\n      automation.dh_presence_notifications:\n",
                      merged)

    def test_seven_notified_event_types(self):
        code = PACKAGE.read_text(encoding="utf-8")
        for event in ("arrival", "departure", "wifi_in", "wifi_lost", "wifi_out", "zone_enter", "zone_leave"):
            self.assertIn("id: " + event, code)
        self.assertEqual(code.count("trigger: event.received"), 7)
        self.assertEqual(code.count("action: script.write2log"), 7)
        self.assertEqual(code.count("action: logbook.log"), 0)
        self.assertEqual(code.count("action: persistent_notification.create"), 0)
        # Source-only GPS events remain in the App, but never duplicate
        # the logical home and information-only geozone notifications.
        self.assertNotIn("id: gps_in", code)
        self.assertNotIn("id: gps_out", code)

    def test_zone_switches_and_explicit_wifi_switch_gate_only_write2log(self):
        code = PACKAGE.read_text(encoding="utf-8")
        self.assertNotIn("switch.dh_presence_app_notify_presence", code)
        self.assertEqual(code.count("trigger.to_state.attributes.zone_key"), 2)
        # A single source of home notices: logical arrival/departure gated
        # by zone.home, never gps_in/out or duplicate zone.home notices.
        self.assertEqual(code.count("switch.dh_presence_app_notify_zone_620b51c29b479984"), 2)
        self.assertEqual(code.count("zone_entity_id != 'zone.home'"), 2)
        self.assertNotIn("switch.dh_presence_app_notify_gps", code)
        self.assertEqual(code.count("entity_id: switch.dh_presence_app_notify_wifi"), 3)
        self.assertEqual(code.count('state: "on"'), 3)
        self.assertEqual(code.count("action: script.write2log"), 7)

    def test_router_wifi_out_wording_and_unknown_without_false_claims(self):
        code = PACKAGE.read_text(encoding="utf-8")
        self.assertIn("id: wifi_lost", code)
        self.assertIn("Wi-Fi не подтверждается", code)
        self.assertIn("Источник Wi-Fi временно недоступен", code)
        self.assertIn("wifi_out now means explicit router device_tracker home -> not_home", code)
        self.assertIn("По данным Wi-Fi-трекера роутера", code)
        self.assertNotIn("выбранными методами PING/ARP", code)
        self.assertNotIn("timeout_minutes", code)
        self.assertNotIn("resident_names.", code)
        self.assertNotIn("dh_presence_app_notification_local_package:\\n", code)

    def test_no_fabricated_home_security_actions(self):
        code = PACKAGE.read_text(encoding="utf-8")
        for bad in (
            "action: input_select.select_option",
            "action: alarm_control_panel.alarm_",
            "action: notify.mobile_app_",
        ):
            self.assertNotIn(bad, code)

    def test_first_last_mode_message_uses_machine_facts(self):
        code = PACKAGE.read_text(encoding="utf-8")
        for required in (
            "trigger.to_state.attributes.first_arrival",
            "trigger.to_state.attributes.last_departure",
            "Статус дома: ПРИСУТСТВИЕ",
            "Статус дома: ОТСУТСТВИЕ",
            "residents_home_after",
        ):
            self.assertIn(required, code)
        engine = CORE.read_text(encoding="utf-8")
        self.assertIn("before_home is Status.NOT_HOME and after_home is Status.HOME", engine)
        self.assertIn("before_home is Status.HOME and after_home is Status.NOT_HOME", engine)

    def test_person_mapping_owned_by_app_and_rendered_directly(self):
        code = PACKAGE.read_text(encoding="utf-8")
        self.assertNotIn("resident_user_names:", code)
        self.assertNotIn("states.person", code)
        self.assertIn("ev.user_name", code)
        self.assertIn("ev.device_name", code)
        runtime = RUNTIME.read_text(encoding="utf-8")
        self.assertIn('"device_tracker": resident.tracker', runtime)
        self.assertIn('"user_name": resident.user_name', runtime)
        self.assertIn('"device_name": resident.name', runtime)

    def test_write2log_data_fields_are_explicit_and_utf8_safe(self):
        # HA 2026.10.1: Jinja tojson can leave escaped emoji surrogate
        # halves in the HA service-data rendering pipeline.
        code = PACKAGE.read_text(encoding="utf-8")
        self.assertEqual(code.count("- action: script.write2log"), 7)
        self.assertEqual(code.count('title: "'), 7)
        self.assertEqual(code.count('message: "'), 7)
        self.assertNotIn("| tojson", code)
        self.assertNotIn("data: >-", code)
        for line in code.splitlines():
            if 'title: "' in line:
                title = line.split('title: "', 1)[1].rsplit('"', 1)[0]
                placeholders = ("{{ person_name }}", "{{ wifi_person_device }}")
                self.assertEqual(sum(title.count(v) for v in placeholders), 1)
                for placeholder in placeholders:
                    title = title.replace(placeholder, "Serzhan")
                title.encode("utf-8")
        for variable in ("person_name:", "wifi_person_device:",
                         "arrival_message:", "departure_message:",
                         "wifi_lost_message:", "wifi_out_message:"):
            self.assertIn(variable, code)
        self.assertIn("if trigger.to_state.attributes.first_arrival", code)
        self.assertIn("if trigger.to_state.attributes.last_departure", code)

    def test_each_write2log_has_only_title_and_message(self):
        import re
        code = PACKAGE.read_text(encoding="utf-8")
        self.assertEqual(code.count("- action: script.write2log"), 7)
        blocks = re.findall(
            r'(?m)^[ ]+data:\n[ ]+title: "[^"\n]+"\n[ ]+message: "[^"\n]+"',
            code,
        )
        self.assertEqual(len(blocks), 7)
        self.assertNotIn("data: >-", code)
        self.assertNotIn("} | tojson }}", code)
