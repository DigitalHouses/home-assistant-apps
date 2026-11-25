import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from copy import deepcopy
from electrica.binding_store import BindingStore, validate_document, decode_json
from electrica.catalog import CatalogError
from electrica.entity_options import parse_rows, project
from electrica.ingress import export_bindings, import_bindings, revision
from electrica.ingress_catalog import target_catalog
from test_ingress import PROFILE, REGISTRIES, STATES, KEY

class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        supervisor=Mock()
        supervisor.read.return_value={"auto_scan_interval":60}
        self.store=BindingStore(supervisor,Path(self.tmp.name)/"bindings.json")
        self.store.write({"switches":"- "+KEY+": {enabled: true, actions: {single: [light.bra]}}"})
        self.app=SimpleNamespace(options=self.store,_scan_lock=threading.Lock(),
           _mutex=threading.RLock(),config=project(PROFILE,self.store.read()),
           target_catalog=target_catalog(REGISTRIES,STATES,PROFILE),_publish_details=Mock())
    def restore(self,doc):
        import_bindings(self.app,{"revision":revision(parse_rows(self.store.read())),"document":doc})
    def test_roundtrip_and_clear(self):
        doc=export_bindings(self.app)
        self.assertEqual(set(doc),{"schema","rows"})
        self.restore({"schema":1,"rows":[]})
        self.assertFalse(self.app.config["rooms"][0]["switches"][0]["enabled"])
        self.restore(doc)
        self.assertEqual(export_bindings(self.app),doc)
        self.assertTrue(self.app.config["rooms"][0]["switches"][0]["enabled"])
    def test_invalid_import_leaves_live_and_disk_untouched(self):
        doc=export_bindings(self.app)
        raw=self.store.path.read_bytes()
        bad=deepcopy(doc);bad["rows"][0]["actions"]={"not_a_key":["light.bra"]}
        with self.assertRaises(CatalogError):self.restore(bad)
        bad=deepcopy(doc);bad["rows"][0]["actions"]={"single":{"assignments":[{"entity_id":"light.bra","operation":"on","data":{"brightness_pct":50}}]}}
        with self.assertRaises(CatalogError):self.restore(bad)
        with self.assertRaises(CatalogError):import_bindings(self.app,{"revision":"stale","document":doc})
        self.assertEqual(self.store.path.read_bytes(),raw)
        self.assertEqual(export_bindings(self.app),doc)


    def test_aqara_v023_export_preserves_all_supported_action_forms(self):
        # Same public schema and action forms as the released v0.2.3 exporter.
        doc = {"schema": 1, "rows": [
            {"entity_id": KEY, "enabled": True, "maintenance_mode": False,
             "actions": {"single": ["light.bra"],
                         "double": {"assignments": [
                             {"entity_id": "light.rgb", "operation": "on",
                              "data": {"rgb_color": [255, 0, 0], "brightness_pct": 50}},
                             {"entity_id": "switch.relay", "operation": "off", "data": {}}]}},
             "disabled_actions": ["double"]},
            {"entity_id": "switch.removed", "enabled": True,
             "keep_mode": {"left": "decoupled/ON"},
             "actions": {
                 "single_left": {"service": "light.toggle", "targets": [
                     {"light.rgb": {"color_temp_kelvin": 3000, "transition": 0.5}}]},
                 "double_left": {"service": "light.turn_on", "targets": ["light.rgb"],
                                 "brightness_pct": 75},
                 "hold_left": ["light.missing"]},
             "maintenance_mode": True}
        ]}
        self.restore(doc)
        self.assertEqual(export_bindings(self.app), doc)
        self.assertEqual(self.app.config["orphan_bindings"], [doc["rows"][1]])
        self.assertNotIn("double", self.app.config["rooms"][0]["switches"][0]["bindings"])
        reopened = BindingStore(self.store.supervisor, self.store.path)
        self.assertEqual(parse_rows(reopened.read()), doc["rows"])

    def test_document_validation_rejects_unrecognised_fields_and_wrong_schema(self):
        original = export_bindings(self.app)
        raw = self.store.path.read_bytes()
        cases = []
        for schema in (True, 1.0, 2, "1"):
            bad = deepcopy(original)
            bad["schema"] = schema
            cases.append(bad)
        bad = deepcopy(original)
        bad["unknown_section"] = []
        cases.append(bad)
        bad = deepcopy(original)
        bad["rows"][0]["unexpected"] = True
        cases.append(bad)
        bad = deepcopy(original)
        bad["rows"].append(deepcopy(bad["rows"][0]))
        cases.append(bad)
        for bad in cases:
            with self.subTest(document=bad):
                with self.assertRaises(CatalogError):
                    self.restore(bad)
                self.assertEqual(self.store.path.read_bytes(), raw)
                self.assertEqual(export_bindings(self.app), original)
                self.store.path.write_text(json.dumps(bad))
                with self.assertRaises(CatalogError):
                    BindingStore(self.store.supervisor, self.store.path)
                self.store.path.write_bytes(raw)

    def test_duplicate_json_keys_are_rejected_on_disk_and_http_decoder(self):
        raw = b'{"schema":1,"rows":[],"rows":[]}'
        with self.assertRaises(CatalogError):
            decode_json(raw)
        self.store.path.write_bytes(raw)
        with self.assertRaises(CatalogError):
            BindingStore(self.store.supervisor, self.store.path)
        self.assertEqual(self.store.path.read_bytes(), raw)

    def test_validation_does_not_alias_caller_document(self):
        doc = export_bindings(self.app)
        verified = validate_document(doc)
        verified["rows"][0]["actions"]["single"].append("light.other")
        self.assertEqual(doc, export_bindings(self.app))

    def test_document_size_limit_is_shared_by_store_and_import(self):
        original = export_bindings(self.app)
        raw = self.store.path.read_bytes()
        with patch("electrica.binding_store.MAX_DOCUMENT_BYTES", 32):
            with self.assertRaises(CatalogError):
                validate_document(original)
            with self.assertRaises(CatalogError):
                self.restore(original)
        self.assertEqual(self.store.path.read_bytes(), raw)
        self.assertEqual(export_bindings(self.app), original)
