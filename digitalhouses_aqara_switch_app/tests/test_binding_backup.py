import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from copy import deepcopy
from aqara_switch.binding_store import BindingStore
from aqara_switch.catalog import CatalogError
from aqara_switch.entity_options import parse_rows, project
from aqara_switch.ingress import export_bindings, import_bindings, revision
from aqara_switch.ingress_catalog import target_catalog
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
