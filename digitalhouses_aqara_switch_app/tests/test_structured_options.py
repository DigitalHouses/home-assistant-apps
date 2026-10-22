"""v0.1.6 clean installation: no migration, entity-keyed YAML actions."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import yaml

from aqara_switch.catalog import CatalogError
from aqara_switch.entity_options import (
    _read_profiles, _save_profiles, parse_rows, render_rows, current, store_scan,
)

IEEE = "0x00158d0000000001"
COORD = "0x00124b002e1330dd"
ENTITY = "switch.livingroomaqaraswitch"


def profiles():
    return {"rooms": [{"area_id": "living", "name": "Гостиная", "switches": [{
        "coordinator_ieee": COORD, "base_topic": "zigbee2mqtt",
        "logical_name": "aqara_switch", "ieee": IEEE, "entity_id": ENTITY,
        "fingerprint": {"vendor": "Aqara", "model": "ABC",
                        "actions": ["single", "double"],
                        "setting_keys": [], "relay_channels": []},
        "settings": {}, "panel_relay": None, "bindings": {}
    }]}]}


class EntityOptionTests(unittest.TestCase):
    def test_empty_config_on_clean_install(self):
        with TemporaryDirectory() as td:
            self.assertEqual(current({"switches": "[]"}, Path(td)/"store.json"), {"rooms": []})

    def test_round_trip_multiple_lights_one_press(self):
        with TemporaryDirectory() as td:
            path = Path(td)/"store.json"
            _save_profiles(path, profiles())
            options = {"switches": """
- switch.livingroomaqaraswitch:
    enabled: true
    actions:
      single:
        - light.dh_aqara_lab_chandelier
        - light.dh_aqara_lab_spots
      double:
        - light.dh_aqara_lab_sconce
"""}
            result = current(options, path)["rooms"][0]["switches"][0]
            self.assertEqual(result["bindings"]["single"]["targets"],
                             ["light.dh_aqara_lab_chandelier", "light.dh_aqara_lab_spots"])
            self.assertEqual(result["bindings"]["double"]["targets"],
                             ["light.dh_aqara_lab_sconce"])
            self.assertEqual(result["entity_id"], ENTITY)
            self.assertEqual(result["ieee"], IEEE)
            self.assertEqual(len(parse_rows({"switches":render_rows(parse_rows(options))})), 1)

    def test_reject_fake_switch_unsupported_action_and_untrusted_target(self):
        with TemporaryDirectory() as td:
            path = Path(td)/"store.json"
            _save_profiles(path, profiles())
            invalid = [
                "- switch.not_adopted: {enabled: true, actions: {}}",
                "- switch.livingroomaqaraswitch: {enabled: true, actions: {long: [light.foo]}}",
                "- switch.livingroomaqaraswitch: {enabled: true, actions: {single: [switch.relay]}}",
                "- switch.livingroomaqaraswitch: {enabled: true, actions: {single: [light.foo, light.foo]}}",
                "- switch.livingroomaqaraswitch: {enabled: true, actions: {single: []}}",
                "- event.aqara: {enabled: true, actions: {}}",
            ]
            for yaml_text in invalid:
                with self.subTest(yaml_text=yaml_text):
                    with self.assertRaises(CatalogError):
                        current({"switches":yaml_text},path)

    def test_explicit_scan_appends_inert_device_without_overwriting_actions(self):
        with TemporaryDirectory() as td:
            path=Path(td)/"store.json"
            options={"switches":"[]"}
            merged=profiles()
            proposed=store_scan(merged,options,path)
            self.assertEqual(parse_rows(proposed),[
                {"entity_id":ENTITY,"enabled":True,"actions":{}}])
            updated=current(proposed,path)
            self.assertEqual(len(updated["rooms"][0]["switches"]),1)
            self.assertEqual(_read_profiles(path),merged)

    def test_schema_contains_short_text_not_ieee_bindings(self):
        config=yaml.safe_load((Path(__file__).resolve().parents[1]/"config.yaml").read_text())
        self.assertEqual(config["version"],"0.1.9")
        self.assertEqual(config["schema"]["switches"],"str")
        self.assertNotIn("bindings",config["schema"])
        self.assertNotIn("configuration_yaml",config["schema"])
        self.assertEqual(config["options"]["switches"].strip(),"[]")


if __name__=="__main__":
    unittest.main()
