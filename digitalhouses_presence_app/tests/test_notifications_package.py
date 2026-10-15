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

    def test_five_notified_event_types(self):
        code = PACKAGE.read_text(encoding="utf-8")
        for event in ("arrival", "departure", "wifi_in", "wifi_lost", "wifi_out"):
            self.assertIn("id: " + event, code)
        self.assertEqual(code.count("trigger: event.received"), 5)
        self.assertEqual(code.count("action: script.write2log"), 5)
        self.assertEqual(code.count("action: logbook.log"), 0)
        self.assertEqual(code.count("action: persistent_notification.create"), 0)
        self.assertNotIn("id: gps_in", code)
        self.assertNotIn("id: gps_out", code)

    def test_unverified_wifi_loss_is_never_called_confirmed_disconnection(self):
        code = PACKAGE.read_text(encoding="utf-8")
        self.assertIn("id: wifi_lost", code)
        self.assertIn("Wi-Fi не подтверждается", code)
        self.assertIn("Это не означает подтверждённое отключение или уход", code)
        self.assertIn("timeout_minutes", code)
        self.assertIn("wifi_out remains reserved", code)
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
            "Режим дома: присутствие",
            "Режим дома: отсутствие",
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
        self.assertIn("event.user_name", code)
        self.assertIn("event.device_name", code)
        runtime = RUNTIME.read_text(encoding="utf-8")
        self.assertIn('"device_tracker": resident.tracker', runtime)
        self.assertIn('"user_name": resident.user_name', runtime)
        self.assertIn('"device_name": resident.name', runtime)

    def test_write2log_data_templates_are_short_and_self_contained(self):
        # Long Jinja conditionals inside service data caused an actual
        # TemplateSyntaxError on HA Core 2026.10.1 in the field.
        code = PACKAGE.read_text(encoding="utf-8")
        lines = code.splitlines()
        templates = [lines[i + 1].strip() for i, line in enumerate(lines[:-1])
                     if line.strip() == "data: >-"]
        self.assertEqual(len(templates), 5)
        for template in templates:
            with self.subTest(template=template):
                self.assertLess(len(template), 170)
                self.assertTrue(template.startswith("{{ {"))
                self.assertTrue(template.endswith("} | tojson }}"))
                self.assertEqual(template.count("{{"), 1)
                self.assertEqual(template.count("}}"), 1)
                self.assertIn("'title':", template)
                self.assertIn("'message':", template)
                self.assertNotIn("trigger.to_state", template)
        for variable in ("arrival_message:", "departure_message:",
                         "wifi_lost_message:"):
            self.assertIn(variable, code)
        self.assertIn("if trigger.to_state.attributes.first_arrival", code)
        self.assertIn("if trigger.to_state.attributes.last_departure", code)

    def test_each_write2log_has_only_title_and_message(self):
        code = PACKAGE.read_text(encoding="utf-8")
        self.assertEqual(code.count("- action: script.write2log"), 5)
        # Every service data field is one validated string template returning
        # a JSON dictionary, not a nested YAML dict that HA rejected.
        self.assertEqual(code.count("data: >-"), 5)
        self.assertEqual(code.count("} | tojson }}"), 5)
        self.assertNotIn("data:\\n                  title:", code)
        self.assertEqual(code.count("'title':"), 5)
        self.assertEqual(code.count("'message':"), 5)
