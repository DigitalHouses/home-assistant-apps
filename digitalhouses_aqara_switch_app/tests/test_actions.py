"""Pure command planning tests for the virtual-light lab."""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rootfs/app"))
try:
    from aqara_switch.actions import plan_action, ActionError
finally:
    sys.path.pop(0)


class ActionPlannerTests(unittest.TestCase):
    def setUp(self):
        self.device = {
            "fingerprint": {"actions": ["single", "double", "hold"]},
            "bindings": {
                "single": {"action": "toggle", "targets": [
                    "light.dh_aqara_lab_chandelier"]},
                "double": {"action": "off", "targets": [
                    "light.dh_aqara_lab_chandelier",
                    "light.dh_aqara_lab_spots",
                    "light.dh_aqara_lab_led_strip"]},
            },
        }

    def test_virtual_lamp_toggle_command(self):
        self.assertEqual(plan_action(self.device, "single"), {
            "service": "light.toggle",
            "target": {"entity_id": ["light.dh_aqara_lab_chandelier"]},
        })

    def test_multiple_virtual_lamps(self):
        call = plan_action(self.device, "double")
        self.assertEqual(call["service"], "light.turn_off")
        self.assertEqual(len(call["target"]["entity_id"]), 3)

    def test_unconfigured_or_unsupported_is_noop(self):
        self.assertIsNone(plan_action(self.device, "hold"))
        self.assertIsNone(plan_action(self.device, "triple"))

    def test_wrong_domain_or_mixed_targets_is_error(self):
        self.device["bindings"]["single"]["targets"] = [
            "light.dh_aqara_lab_spots", "switch.another"]
        with self.assertRaisesRegex(ActionError, "same HA domain"):
            plan_action(self.device, "single")

    def test_no_arbitrary_service_execution(self):
        self.device["bindings"]["single"]["action"] = "shutdown"
        with self.assertRaisesRegex(ActionError, "not permitted"):
            plan_action(self.device, "single")

    def test_no_invalid_target(self):
        self.device["bindings"]["single"]["targets"] = ["light.*"]
        with self.assertRaisesRegex(ActionError, "Invalid HA"):
            plan_action(self.device, "single")


if __name__ == "__main__":
    unittest.main()
