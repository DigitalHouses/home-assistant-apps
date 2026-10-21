"""Structured Supervisor UI / Adopt migration regression and no-loss guarantees."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import yaml

from aqara_switch.catalog import CatalogError, validate_config
from aqara_switch.configuration import parse_configuration
from aqara_switch.structured_options import (
    _read_profiles, _save_profiles, binding_rows, current, migrate,
    project, store_scan, switch_rows,
)

COORD = "0x00124b002e1330dd"
IEEES = ["0x54ef44100017c840", "0x54ef441000dc08bb"]
LIGHT = "light.dh_aqara_lab_chandelier"


def old_config():
    return {"rooms": [
        {"area_id": "gostinaia", "name": "Гостиная", "switches": [
            {"coordinator_ieee": COORD, "base_topic": "zigbee2mqtt",
             "logical_name": "ths_livingroom", "ieee": IEEES[0],
             "fingerprint": {"vendor": "Aqara", "model": "TH-S04D",
                             "actions": ["single_center", "double_plus"],
                             "setting_keys": ["operation_mode"],
                             "relay_channels": []},
             "settings": {"operation_mode": "decoupled"},
             "bindings": {"single_center": {"action": "toggle", "targets": [LIGHT]}},
             "panel_relay": None},
        ]},
        {"area_id": None, "name": "Без комнаты", "switches": [
            {"coordinator_ieee": COORD, "base_topic": "zigbee2mqtt",
             "logical_name": "aqara_battery_button", "ieee": IEEES[1],
             "fingerprint": {"vendor": "Aqara", "model": "WXKG13LM",
                             "actions": ["single", "double"],
                             "setting_keys": [], "relay_channels": []},
             "settings": {}, "bindings": {}, "panel_relay": None},
        ]},
    ]}


class FakeSupervisor:
    def __init__(self, source=None, *, fail_writes=False):
        self.options = {"log_level": "info", "switches": [], "bindings": []}
        self.legacy = {"configuration_yaml": yaml.safe_dump(
            source or old_config(), allow_unicode=True, sort_keys=False)}
        self.calls = 0
        self.fail_writes = fail_writes

    def read(self):
        return deepcopy(self.options)

    def read_raw(self):
        return deepcopy(self.legacy)

    def write(self, options):
        self.calls += 1
        if self.fail_writes:
            raise RuntimeError("Supervisor refused transaction")
        self.options = deepcopy(options)


class StructuredOptionsTest(TestCase):
    def test_migrate_exact_two_devices_settings_and_light_bindings(self):
        with TemporaryDirectory() as td:
            store = Path(td) / "adopted_switches.json"
            sup = FakeSupervisor()
            opts = migrate(sup, store)
            self.assertEqual(sup.calls, 1)
            self.assertEqual(len(opts["switches"]), 2)
            self.assertEqual(opts["bindings"], [
                {"ieee": IEEES[0], "press": "single_center", "light": LIGHT}])
            self.assertEqual(_read_profiles(store), validate_config(old_config()))
            actual = project(_read_profiles(store), opts)
            self.assertEqual(actual["rooms"][0]["switches"][0]["settings"],
                             {"operation_mode": "decoupled"})
            self.assertEqual(actual["rooms"][0]["switches"][0]["bindings"],
                             old_config()["rooms"][0]["switches"][0]["bindings"])
            self.assertEqual(actual["rooms"][1]["name"], "Без комнаты")
            self.assertTrue((Path(td) / "legacy_configuration_yaml.txt").exists())
            self.assertTrue((Path(td) / "structured_options_migrated").exists())
            self.assertEqual(migrate(sup, store), opts)
            self.assertEqual(sup.calls, 1, "migration must be idempotent")

    def test_failed_supervisor_write_preserves_old_and_retry(self):
        with TemporaryDirectory() as td:
            store = Path(td) / "adopted_switches.json"
            sup = FakeSupervisor(fail_writes=True)
            with self.assertRaisesRegex(RuntimeError, "refused"):
                migrate(sup, store)
            self.assertEqual(sup.options["switches"], [])
            self.assertTrue(store.exists())
            self.assertFalse((Path(td) / "structured_options_migrated").exists())
            sup.fail_writes = False
            migrate(sup, store)
            self.assertEqual(sup.calls, 2)
            self.assertEqual(len(sup.options["switches"]), 2)

    def test_block_incompatible_existing_bindings_without_changes(self):
        with TemporaryDirectory() as td:
            store = Path(td) / "adopted_switches.json"
            invalid = old_config()
            invalid["rooms"][0]["switches"][0]["bindings"]["single_center"] = {
                "action": "toggle", "targets": ["switch.real_relay"]}
            sup = FakeSupervisor(invalid)
            with self.assertRaisesRegex(CatalogError, "non-light.toggle"):
                migrate(sup, store)
            self.assertEqual(sup.calls, 0)
            self.assertFalse(store.exists())

    def test_owner_changes_binding_and_enabled_without_mutating_adopt(self):
        with TemporaryDirectory() as td:
            store = Path(td) / "adopted_switches.json"
            original = old_config()
            _save_profiles(store, original)
            opts = {"switches": switch_rows(original),
                    "bindings": binding_rows(original)}
            opts["switches"][0]["enabled"] = False
            opts["bindings"][0]["light"] = "light.dh_aqara_lab_spots"
            view = project(_read_profiles(store), opts)
            self.assertFalse(view["rooms"][0]["switches"][0]["enabled"])
            self.assertEqual(view["rooms"][0]["switches"][0]["bindings"]["single_center"]
                             ["targets"], ["light.dh_aqara_lab_spots"])
            self.assertEqual(_read_profiles(store), validate_config(original))

    def test_reject_unadopted_unsupported_and_duplicate_bindings(self):
        with TemporaryDirectory() as td:
            store = Path(td) / "adopted_switches.json"
            _save_profiles(store, old_config())
            opts = {"switches": switch_rows(old_config()), "bindings": []}
            for bad in [
                {"ieee": "0x1234567890abcdef", "press": "single", "light": LIGHT},
                {"ieee": IEEES[0], "press": "triple", "light": LIGHT},
                {"ieee": IEEES[0], "press": "single_center", "light": "switch.real_relay"},
            ]:
                with self.assertRaises(CatalogError):
                    project(_read_profiles(store), {**opts, "bindings": [bad]})
            one = {"ieee": IEEES[0], "press": "single_center", "light": LIGHT}
            with self.assertRaisesRegex(CatalogError, "Duplicate binding"):
                project(_read_profiles(store), {**opts, "bindings": [one, one]})

    def test_new_scan_appends_without_erasing_old_enabled_or_bindings(self):
        with TemporaryDirectory() as td:
            store = Path(td) / "adopted_switches.json"
            old = old_config()
            _save_profiles(store, old)
            opts = {"switches": switch_rows(old), "bindings": binding_rows(old)}
            opts["switches"][0]["enabled"] = False
            additional = deepcopy(old)
            additional["rooms"][1]["switches"].append({
                **deepcopy(old["rooms"][1]["switches"][0]),
                "logical_name": "third_aqara",
                "ieee": "0x54ef441000dc08bc",
            })
            result = store_scan(additional, opts, store)
            self.assertEqual(len(result["switches"]), 3)
            self.assertFalse(result["switches"][0]["enabled"])
            self.assertEqual(result["bindings"], opts["bindings"])
            self.assertEqual(len(_read_profiles(store)["rooms"][1]["switches"]), 2)
            self.assertEqual(len(current(result, store)["rooms"][1]["switches"]), 2)

    def test_supervisor_schema_is_native_form(self):
        path = Path(__file__).resolve().parents[1] / "config.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(config["version"], "0.1.5")
        self.assertNotIn("configuration_yaml", config["schema"])
        self.assertNotIn("configuration_yaml", config["options"])
        self.assertEqual(set(config["schema"]["switches"][0]),
                         {"ieee", "name", "enabled"})
        self.assertEqual(set(config["schema"]["bindings"][0]),
                         {"ieee", "press", "light"})
        self.assertEqual(config["options"]["switches"], [])
        self.assertEqual(config["options"]["bindings"], [])
