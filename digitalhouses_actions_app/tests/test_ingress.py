"""New Ingress configuration and runtime planning regression tests."""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from copy import deepcopy

from actions.binding_store import BindingStore
from actions.catalog import CatalogError
from actions.control import light_commands
from actions.entity_options import project, parse_rows
from actions.ingress import save_device, revision, validate_assignment
from actions.ingress_catalog import target_catalog, safe_switch_targets, normalize
from actions.light_rules import parse_rule
from actions.scan import scan_once
from actions.operation_ui import AppCard, latest_release
from test_scan_integration import snap, Registry, IEEE, COORD

KEY = "switch.aqara_button"
PROFILE = {"rooms":[{"name":"Гостиная","area_id":"living","switches":[{
    "entity_id":KEY,"logical_name":"aqara_button","coordinator_ieee":COORD,
    "base_topic":"zigbee2mqtt","ieee":IEEE,"settings":{},
    "fingerprint":{"model":"W100","actions":["single","double"]}}]}]}
ASSIGNMENTS = [
    {"entity_id":"light.rgb","operation":"on","data":{"rgb_color":[255,0,0],"brightness_pct":50}},
    {"entity_id":"light.bra","operation":"off","data":{}},
    {"entity_id":"switch.relay","operation":"toggle","data":{}},
]
REGISTRIES = (
    [{"id":"source","area_id":"living","identifiers":[["mqtt","zigbee2mqtt_"+IEEE]],"connections":[]},
     {"id":"target","area_id":"living","identifiers":[],"connections":[]}],
    [{"area_id":"living","name":"Гостиная"}],
    [{"entity_id":"switch.input_relay","device_id":"source","disabled_by":None},
     {"entity_id":"switch.relay","device_id":"target","disabled_by":None},
     {"entity_id":"light.rgb","device_id":"target","disabled_by":None},
     {"entity_id":"light.bra","device_id":"target","disabled_by":None}],
)
STATES=[
    {"entity_id":"light.rgb","state":"on","attributes":{"friendly_name":"RGB","supported_color_modes":["rgb","color_temp"],"min_color_temp_kelvin":2700,"max_color_temp_kelvin":6500,"supported_features":32}},
    {"entity_id":"light.bra","state":"off","attributes":{"supported_color_modes":["onoff"]}},
    {"entity_id":"switch.relay","state":"on","attributes":{}},
    {"entity_id":"switch.input_relay","state":"on","attributes":{}},
]

class IngressTests(unittest.TestCase):
    def test_individual_operations_and_domains(self):
        rule=parse_rule({"assignments":ASSIGNMENTS})
        sw={"fingerprint":{"actions":["single"]},"bindings":{"single":rule}}
        calls=light_commands(sw,"single")
        self.assertEqual([c["service"] for c in calls],["light.turn_on","light.turn_off","switch.toggle"])
        self.assertEqual(calls[0]["data"]["rgb_color"],[255,0,0])
        self.assertIsNone(light_commands(sw,"double"))

    def test_registry_capabilities_and_protected_relay(self):
        catalog=target_catalog(REGISTRIES,STATES,PROFILE)
        self.assertNotIn("switch.input_relay",catalog)
        self.assertEqual(safe_switch_targets(REGISTRIES,PROFILE),{"switch.relay"})
        self.assertTrue(catalog["light.rgb"]["rgb"])
        self.assertTrue(catalog["light.rgb"]["cct"])
        self.assertFalse(catalog["light.bra"]["brightness"])
        self.assertEqual(catalog["light.rgb"]["area"],"Гостиная")
        validate_assignment(ASSIGNMENTS[0],catalog)
        for invalid in [
            {"entity_id":"light.rgb","operation":"on","data":{"color_temp_kelvin":2000}},
            {"entity_id":"light.bra","operation":"on","data":{"brightness_pct":40}},
            {"entity_id":"switch.relay","operation":"on","data":{"brightness_pct":40}},
            {"entity_id":"switch.input_relay","operation":"on","data":{}},
        ]:
            with self.assertRaises(CatalogError):
                validate_assignment(invalid,catalog)

    def test_hot_save_disable_and_restart(self):
        with tempfile.TemporaryDirectory() as td:
            supervisor=Mock()
            supervisor.read.return_value={"switches":"- "+KEY+": {enabled: true, actions: {single: [light.bra]}}"}
            store=BindingStore(supervisor,Path(td)/"bindings.json")
            store.write({"switches":"- "+KEY+": {enabled: true, actions: {single: [light.bra]}}"})
            app=SimpleNamespace(options=store,_scan_lock=threading.Lock(),_mutex=threading.RLock(),
                 config=project(PROFILE,store.read()),target_catalog=target_catalog(REGISTRIES,STATES,PROFILE),
                 _publish_details=Mock())
            payload={"id":KEY,"revision":revision(parse_rows(store.read())),"enabled":True,
                     "bindings":{"single":ASSIGNMENTS},"disabled_actions":[]}
            save_device(app,payload)
            self.assertEqual(app.config["rooms"][0]["switches"][0]["bindings"]["single"]["target_operations"]["switch.relay"],"toggle")
            # stale editor cannot overwrite settings
            with self.assertRaises(CatalogError):
                save_device(app,payload)
            payload["revision"]=revision(parse_rows(store.read()))
            payload["disabled_actions"]=["single"]
            save_device(app,payload)
            self.assertEqual(app.config["rooms"][0]["switches"][0]["bindings"],{})
            self.assertIn("single",app.config["rooms"][0]["switches"][0]["configured_bindings"])
            saved=BindingStore(supervisor,store.path)
            self.assertEqual(normalize(parse_rows(saved.read())[0]["actions"]["single"]),ASSIGNMENTS)
            self.assertEqual(parse_rows(saved.read())[0]["disabled_actions"],["single"])
            supervisor.write.assert_not_called()

    def test_scan_preserves_stable_key_after_rename(self):
        with tempfile.TemporaryDirectory() as td:
            supervisor=Mock()
            supervisor.read.return_value={"switches":"[]"}
            store=BindingStore(supervisor,Path(td)/"bindings.json")
            with patch("actions.scan.STORE_PATH",Path(td)/"profiles.json"):
                first,_=scan_once([snap()],store,Registry(entities=[]))
                sw=first["rooms"][0]["switches"][0]
                self.assertEqual(sw["entity_id"],KEY)
                self.assertFalse(sw["enabled"]) # auto scan is not permission to actuate
                rows=parse_rows(store.read())
                rows[0]["enabled"]=True
                rows[0]["actions"]={"single":["light.bra"]}
                from actions.entity_options import render_rows
                store.write({**store.read(),"switches":render_rows(rows)})
                renamed,_=scan_once([snap(name="renamed_button")],store,Registry(entities=[]))
                sw=renamed["rooms"][0]["switches"][0]
                self.assertEqual(sw["entity_id"],KEY)
                self.assertEqual(sw["logical_name"],"renamed_button")
                self.assertEqual(sw["bindings"]["single"]["targets"],["light.bra"])
                self.assertEqual(sum(len(r["switches"]) for r in renamed["rooms"]),1)

    def test_aggregate_operation_lifecycle(self):
        events=[]
        card=AppCard(events.append,result_seconds=60)
        self.assertTrue(card.begin("refresh"))
        self.assertFalse(card.begin("check"))
        self.assertTrue(card.finish("refresh",measured_seconds=2.5))
        self.assertEqual([e["state"] for e in events],["running","success"])
        self.assertEqual(events[-1]["duration_seconds"],2.5)
        card._reset_success(card._generation)
        self.assertEqual(events[-1]["state"],"idle")
        self.assertTrue(card.begin("check"))
        card.finish("check",error="offline")
        self.assertEqual(events[-1]["state"],"error")

class SwitchDispatchTests(unittest.TestCase):
    def test_switch_target_and_protected_input_relay(self):
        from test_ha_native_output import NativeLightIntegration, TV
        from test_lab_rest_fallback import PROFILE as SOURCE_PROFILE
        harness=NativeLightIntegration()
        app,ha,registry=harness.build([TV])
        sw=app.config["rooms"][0]["switches"][0]
        ieee=sw["ieee"]
        registry.fetch.return_value=(
            [{"id":"source","identifiers":[["mqtt","zigbee2mqtt_"+ieee]],"connections":[]},
             {"id":"target","identifiers":[],"connections":[]}],[],
            [{"entity_id":"switch.relay","device_id":"target","disabled_by":None},
             {"entity_id":"switch.input_relay","device_id":"source","disabled_by":None}])
        ha.read_switch_state.return_value="off"
        sw["bindings"]["double"]=parse_rule({"assignments":[
            {"entity_id":"switch.relay","operation":"on","data":{}},
            {"entity_id":"switch.input_relay","operation":"off","data":{}},
        ]})
        results,mqtt=harness.run_button(app)
        self.assertEqual(mqtt,[])
        self.assertEqual(results[0]["state"],"partial")
        ha.execute_switch.assert_called_once_with("switch.relay","on")
