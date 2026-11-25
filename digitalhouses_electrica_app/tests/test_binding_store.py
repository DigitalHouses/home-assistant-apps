import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from electrica.binding_store import BindingStore
from electrica.entity_options import project, parse_rows
from electrica.catalog import CatalogError

YAML = """
- switch.aqara_button:
    enabled: true
    actions:
      single:
        service: light.toggle
        targets:
          - light.led:
              rgb_color: [255, 0, 0]
              brightness_pct: 80
              transition: 0.5
      double:
        - light.bra
- switch.th_livingroom_temperature:
    enabled: true
    actions:
      single_plus:
        - light.gledopto_led
"""

class StoreTests(unittest.TestCase):
    def test_first_start_ignores_legacy_yaml_and_preserves_saved_assignments(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bindings.json"
            supervisor = Mock()
            supervisor.read.return_value = {"switches": YAML}
            store = BindingStore(supervisor, path)
            self.assertEqual(parse_rows(store.read()), [])
            supervisor.read_raw.assert_not_called()
            store.write({"switches": YAML})
            self.assertEqual(parse_rows(store.read()), parse_rows({"switches": YAML}))
            self.assertEqual(json.loads(path.read_text())["schema"], 1)
            supervisor.read.return_value = {"switches": "[]"}
            self.assertEqual(parse_rows(BindingStore(supervisor, path).read()),
                             parse_rows({"switches": YAML}))
            profile = {"rooms":[{"area_id":None,"switches":[{
                "entity_id":"switch.aqara_button", "coordinator_ieee":"0x00124b002e1330dd",
                "ieee":"0x00158d0000000001","logical_name":"aqara_button",
                "fingerprint":{"actions":["single","double"]},"settings":{}}]}]}
            active = project(profile, store.read())
            sw = active["rooms"][0]["switches"][0]
            self.assertTrue(sw["enabled"])
            self.assertEqual(sw["bindings"]["single"]["target_data"]["light.led"]["brightness_pct"], 80)
            self.assertEqual(active["binding_problems"][0]["object_name"], "switch.th_livingroom_temperature")
            supervisor.write.assert_not_called()

    def test_removed_schema_never_reads_raw_options(self):
        with tempfile.TemporaryDirectory() as td:
            supervisor = Mock()
            supervisor.read.return_value = {"auto_scan_interval":60}
            supervisor.read_raw.return_value = {"switches": YAML}
            store = BindingStore(supervisor, Path(td)/"bindings.json")
            self.assertEqual(parse_rows(store.read()),[])
            supervisor.read_raw.assert_not_called()

    def test_corrupt_store_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"bindings.json"
            path.write_text("{broken")
            with self.assertRaises(CatalogError):
                BindingStore(Mock(),path)
            self.assertEqual(path.read_text(),"{broken")

    def test_save_does_not_touch_supervisor(self):
        with tempfile.TemporaryDirectory() as td:
            supervisor=Mock()
            supervisor.read.return_value={"switches":YAML}
            store=BindingStore(supervisor,Path(td)/"bindings.json")
            store.write({"switches":"[]"})
            self.assertEqual(parse_rows(store.read()),[])
            supervisor.write.assert_not_called()
