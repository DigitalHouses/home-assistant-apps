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

    def test_exactly_four_notified_transition_types(self):
        code = PACKAGE.read_text(encoding="utf-8")
        for event in ("arrival", "departure", "wifi_in", "wifi_out"):
            self.assertIn("id: " + event, code)
        self.assertEqual(code.count("trigger: event.received"), 4)
        self.assertEqual(code.count("action: logbook.log"), 4)
        self.assertEqual(code.count("action: persistent_notification.create"), 4)
        self.assertNotIn("id: gps_in", code)
        self.assertNotIn("id: gps_out", code)

    def test_no_fabricated_home_security_actions(self):
        code = PACKAGE.read_text(encoding="utf-8")
        for bad in (
            "action: input_select.select_option",
            "action: alarm_control_panel.alarm_",
            "action: script.write2log",
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

    def test_user_name_is_resolved_not_guessed(self):
        code = PACKAGE.read_text(encoding="utf-8")
        self.assertIn("resident_user_names", code)
        self.assertIn("states.person", code)
        self.assertIn("e.device_tracker", code)
        self.assertIn("e.resident_name", code)
        self.assertIn("without a verified name", code.lower())
        runtime = RUNTIME.read_text(encoding="utf-8")
        self.assertIn('"device_tracker": resident.tracker', runtime)
