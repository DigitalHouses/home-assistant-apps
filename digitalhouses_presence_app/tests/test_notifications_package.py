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

    def test_seven_notified_event_types(self):
        code = PACKAGE.read_text(encoding="utf-8")
        for event in ("arrival", "departure", "gps_in", "gps_out", "wifi_in", "wifi_lost", "wifi_out"):
            self.assertIn("id: " + event, code)
        self.assertEqual(code.count("trigger: event.received"), 7)
        self.assertEqual(code.count("action: script.write2log"), 7)
        self.assertEqual(code.count("action: logbook.log"), 0)
        self.assertEqual(code.count("action: persistent_notification.create"), 0)
        self.assertIn("id: gps_in", code)
        self.assertIn("id: gps_out", code)

    def test_three_mqtt_switches_gate_only_write2log_notifications(self):
        code = PACKAGE.read_text(encoding="utf-8")
        self.assertEqual(code.count("entity_id: switch.dh_presence_app_notify_presence"), 2)
        self.assertEqual(code.count("entity_id: switch.dh_presence_app_notify_gps"), 2)
        self.assertEqual(code.count("entity_id: switch.dh_presence_app_notify_wifi"), 3)
        self.assertEqual(code.count('state: "on"'), 7)
        self.assertEqual(code.count("action: script.write2log"), 7)

    def test_unverified_wifi_loss_is_never_called_confirmed_disconnection(self):
        code = PACKAGE.read_text(encoding="utf-8")
        self.assertIn("id: wifi_lost", code)
        self.assertIn("Wi-Fi не подтверждается", code)
        self.assertIn("Это не означает подтверждённое отключение или уход", code)
        self.assertIn("timeout_minutes", code)
        self.assertIn("wifi_out means 15m of completed ARP", code)
        self.assertIn("wifi_out_message:", code)
        self.assertIn("не доказательство отключения Wi-Fi", code)
        self.assertNotIn("resident_names.", code)
        self.assertNotIn("dh_presence_app_notification_local_package:\n", code)

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
                self.assertEqual(title.count("{{ person_device }}"), 1)
                title.replace("{{ person_device }}", "Serzhan (13ProMAX .SKY)").encode("utf-8")
        for variable in ("arrival_message:", "departure_message:",
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
