"""Read-only first-stage acceptance tests; no HA or Zigbee hardware needed."""
import unittest
from copy import deepcopy

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rootfs" / "app"))
try:
    from aqara_switch.catalog import (
        CatalogError, candidate_from_mqtt, import_new, resolve_hardware,
        validate_config, decode_bridge_devices,
    )
finally:
    sys.path.pop(0)

COORD = "0x00124b002e1330dd"
OLD_IEEE = "0x00158d0000000001"
NEW_IEEE = "0x00158d0000000002"


def device(ieee=OLD_IEEE, name="switch_livingroom", model="WXKG17LM", *, wired=False):
    exposes = [
        {"type": "enum", "name": "action", "property": "action", "access": 1,
         "values": ["single_left", "single_right", "double_left"]},
    ]
    if wired:
        exposes.append({"type": "enum", "name": "operation_mode",
                        "property": "operation_mode", "access": 3,
                        "values": ["decoupled", "control_relay"]})
        exposes.append({"type": "switch", "features": [
            {"type": "binary", "property": "state_left", "access": 7}]})
    return {
        "ieee_address": ieee, "type": "Router" if wired else "EndDevice",
        "friendly_name": name,
        "model_id": "lumi.remote.test",
        "definition": {"vendor": "Aqara", "model": model, "exposes": exposes},
    }


def candidate(d=None, state=None):
    return candidate_from_mqtt(
        d or device(), coordinator_ieee=COORD, base_topic="zigbee2mqtt",
        reported_state=state,
    )


class CatalogTest(unittest.TestCase):
    def test_battery_button_needs_no_relay_snapshot(self):
        obj = candidate()
        self.assertEqual(obj["settings"], {})
        self.assertEqual(obj["fingerprint"]["actions"], [
            "double_left", "single_left", "single_right"])
        self.assertEqual(obj["fingerprint"]["relay_channels"], [])

    def test_wired_device_requires_confirmed_setting(self):
        with self.assertRaisesRegex(CatalogError, "not confirmed"):
            candidate(device(wired=True), {})
        obj = candidate(device(wired=True), {"operation_mode": "decoupled"})
        self.assertEqual(obj["settings"], {"operation_mode": "decoupled"})
        self.assertEqual(obj["fingerprint"]["relay_channels"], ["state_left"])

    def test_reject_other_vendors_and_sensors(self):
        foreign = device()
        foreign["definition"]["vendor"] = "SONOFF"
        self.assertIsNone(candidate(foreign))
        sensor = device()
        sensor["definition"]["exposes"] = [{"type": "numeric", "property": "temperature"}]
        self.assertIsNone(candidate(sensor))

    def test_import_new_and_repeat_without_changes(self):
        before = {"rooms": []}
        after, report = import_new(before, [candidate()], {
            OLD_IEEE: {"area_id": "living", "name": "Гостиная"}
        })
        self.assertEqual(before, {"rooms": []})
        self.assertEqual(report["added"], [{"name": "switch_livingroom", "area_id": "living"}])
        self.assertEqual(after["rooms"][0]["area_id"], "living")
        switch = after["rooms"][0]["switches"][0]
        switch["bindings"]["single_left"] = {
            "action": "toggle", "target": "light.dh_aqara_lab_chandelier"}
        switch["panel_relay"] = "switch.tongou_livingroom_lights"
        restored, repeat = import_new(after, [candidate()], {
            OLD_IEEE: {"area_id": "changed", "name": "Другая комната"}
        })
        self.assertEqual(restored, after)
        self.assertEqual(repeat["skipped"], ["switch_livingroom"])
        self.assertEqual(repeat["added"], [])

    def test_known_ieee_with_renamed_name_is_a_problem(self):
        initial, _ = import_new({"rooms": []}, [candidate()], {})
        renamed = candidate(device(name="new_name"))
        after, report = import_new(initial, [renamed], {})
        self.assertEqual(after, initial)
        self.assertEqual(report["problems"][0]["reason"], "known_ieee_renamed")

    def test_replacement_same_fingerprint(self):
        saved = candidate()
        observed = candidate(device(ieee=NEW_IEEE))
        self.assertEqual(resolve_hardware(saved, [observed]), {
            "status": "replacement", "observed_ieee": NEW_IEEE
        })
        self.assertEqual(resolve_hardware(saved, [saved])["status"], "same")

    def test_replacement_changed_model_is_blocked(self):
        saved = candidate()
        observed = candidate(device(ieee=NEW_IEEE, model="different_model"))
        self.assertEqual(resolve_hardware(saved, [observed])["status"], "incompatible")
        self.assertEqual(resolve_hardware(saved, [])["status"], "missing")
        self.assertEqual(resolve_hardware(saved, [saved, saved])["status"], "ambiguous")

    def test_missing_ha_area_is_explicit_unassigned(self):
        result, report = import_new({"rooms": []}, [candidate()], {})
        self.assertIsNone(result["rooms"][0]["area_id"])
        self.assertEqual(result["rooms"][0]["name"], "Без комнаты")
        self.assertIsNone(report["added"][0]["area_id"])

    def test_import_never_mutates_user_config(self):
        before = {"rooms": []}
        snap = deepcopy(before)
        _ = import_new(before, [candidate()], {})
        self.assertEqual(before, snap)

    def test_duplicate_logical_keys_rejected(self):
        obj, _ = import_new({"rooms": []}, [candidate()], {})
        obj["rooms"][0]["switches"].append(deepcopy(obj["rooms"][0]["switches"][0]))
        with self.assertRaisesRegex(CatalogError, "Duplicate"):
            validate_config(obj)

    def test_invalid_mqtt_payload_fails(self):
        with self.assertRaises(CatalogError):
            decode_bridge_devices(b'{"not":"devices"}')

    def test_network_is_part_of_identity(self):
        first = candidate()
        second = candidate(device(ieee=NEW_IEEE))
        second["coordinator_ieee"] = "0x00124b002e1330de"
        result, report = import_new({"rooms": []}, [first, second], {})
        self.assertEqual(len(result["rooms"][0]["switches"]), 2)
        self.assertEqual(len(report["added"]), 2)


if __name__ == "__main__":
    unittest.main()
