"""Actions per-key configuration and verified manufacturer capabilities."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from copy import deepcopy

from actions.binding_store import BindingStore
from actions.catalog import CatalogError, candidate_from_mqtt, has_device_power
from actions.control import verified_adopted_switch
from actions.entity_options import project, parse_rows, render_rows
from actions.ingress import save_device, revision, snapshot, export_bindings
from actions.ingress_catalog import normalize
from actions.keeper_runtime import tick
from actions.mode_keeper import capabilities, mode_action_allowed, next_repair
from actions.scan import scan_once
from test_mode_keeper import wired, state, saved, profiles, SimpleApp, BASE, COORD, IEEE, NAME, ENTITY, battery
from test_scan_integration import Registry
from test_ingress import REGISTRIES, STATES
from actions.ingress_catalog import target_catalog


class KeyPolicyTests(unittest.TestCase):
    def test_mixed_key_policy_and_combination_actions(self):
        sw = saved()
        sw["keep_mode"] = {"left":"decoupled", "right":"control_relay"}
        live = state(left_relay="OFF")
        features = capabilities(wired())
        self.assertTrue(mode_action_allowed(sw,"single_left",live,features,False))
        self.assertFalse(mode_action_allowed(sw,"single_right",live,features,False))
        self.assertFalse(mode_action_allowed(sw,"double_both",live,features,False))
        self.assertIsNone(next_repair(sw["keep_mode"],features,live,False))

    def test_physical_keeper_never_probes_or_writes_relay(self):
        app = SimpleApp()
        sw = app.config["rooms"][0]["switches"][0]
        sw["keep_mode"] = {"left":"control_relay"}
        app._fresh_fields = {(BASE,NAME,"operation_mode_left")}
        app._networks[BASE]["states"][NAME] = {"operation_mode_left":"decoupled"}
        tick(app,1)
        tick(app,1.61)
        self.assertEqual(app.sent,[(BASE+"/"+NAME+"/set",
                                    {"operation_mode_left":"control_relay"},False)])
        app._networks[BASE]["states"][NAME]["operation_mode_left"]="control_relay"
        tick(app,100)
        self.assertEqual(len(app.sent),1)

    def test_logical_without_power_and_maintenance(self):
        features = capabilities(wired())
        live = state(left_relay="OFF")
        self.assertIsNone(next_repair({"left":"decoupled"},features,live,False))
        self.assertEqual(next_repair({"left":"decoupled"},features,live,True),
                         ("operation_mode_left","control_relay"))
        self.assertEqual(next_repair({"left":"decoupled/ON"},features,live,False),
                         ("state_left","ON"))

    def test_keeper_offline_blocks_write(self):
        app=SimpleApp()
        app._networks[BASE]["states"][NAME]=state(left="control_relay")
        app._networks[BASE]["bridge_state"]="offline"
        tick(app,1);tick(app,100)
        self.assertEqual(app.sent,[])

    def test_foreign_remote_verified_but_output_not_supported(self):
        dev=battery()
        dev["definition"]["vendor"]="SONOFF"
        sw=candidate_from_mqtt(dev,coordinator_ieee=COORD,base_topic=BASE,reported_state={})
        self.assertTrue(verified_adopted_switch(sw,dev,COORD,BASE))
        self.assertTrue(mode_action_allowed(sw,"single",{},capabilities(dev),False))
        dev["definition"]["exposes"].append({"type":"binary","property":"state","access":7})
        self.assertFalse(verified_adopted_switch(sw,dev,COORD,BASE))

    def test_scan_discovers_channels_and_only_aggregate_watts(self):
        dev=wired()
        dev["definition"]["exposes"].append({"type":"numeric","property":"power","unit":"W","access":1})
        self.assertTrue(has_device_power(dev))
        with tempfile.TemporaryDirectory() as td:
            supervisor=Mock();supervisor.read.return_value={}
            store=BindingStore(supervisor,Path(td)/"bindings.json")
            snap={"base_topic":BASE,"coordinator_ieee":COORD,
                  "devices":json.dumps([{"type":"Coordinator","ieee_address":COORD},dev]).encode(),
                  "states":{NAME:state()}}
            with patch("actions.scan.STORE_PATH",Path(td)/"profiles.json"):
                cfg,_=scan_once([snap],store,Registry(entities=[],ieee=IEEE))
                sw=cfg["rooms"][0]["switches"][0]
                self.assertEqual(sw["mode_channels"],["left","right"])
                self.assertTrue(sw["power_meter"])
                self.assertFalse(sw["enabled"])
                self.assertEqual(sw["keep_mode"],{})
        dev["definition"]["exposes"][-1]["endpoint"]="left"
        self.assertFalse(has_device_power(dev))

    def test_ingress_requires_removal_of_physical_actions_and_applies_atomically(self):
        with tempfile.TemporaryDirectory() as td:
            supervisor=Mock();supervisor.read.return_value={}
            store=BindingStore(supervisor,Path(td)/"bindings.json")
            rows=[{"entity_id":ENTITY,"enabled":True,"keep_mode":{"left":"decoupled/ON"},
                   "actions":{"single_left":["light.bra"]}}]
            store.write({"switches":render_rows(rows)})
            profile=profiles(); profile["rooms"][0]["switches"][0]["mode_channels"]=["left","right"]
            cfg=project(profile,store.read())
            app=SimpleNamespace(options=store,_scan_lock=threading.Lock(),_mutex=threading.RLock(),
                 config=cfg,target_catalog=target_catalog(REGISTRIES,STATES,profile),
                 device_details=[],_last_details_payload=None,_scan={},_previous={},version="0.2.3",
                 _publish_details=Mock())
            payload={"id":ENTITY,"enabled":True,"revision":revision(parse_rows(store.read())),
                     "keep_mode":{"left":"control_relay","right":"decoupled"},
                     "bindings":{"single_left":normalize(["light.bra"])},
                     "disabled_actions":["single_left"]}
            raw=store.path.read_bytes()
            with self.assertRaises(CatalogError):save_device(app,payload)
            self.assertEqual(store.path.read_bytes(),raw)
            payload["bindings"]={"single_right":normalize(["light.bra"])}
            payload["disabled_actions"]=[]
            save_device(app,payload)
            sw=app.config["rooms"][0]["switches"][0]
            self.assertEqual(sw["keep_mode"],payload["keep_mode"])
            self.assertEqual(set(sw["bindings"]),{"single_right"})
            d=snapshot(app)["devices"][0]
            self.assertEqual(d["key_modes"],payload["keep_mode"])
            self.assertEqual(d["actions"],["single_right"])
            self.assertEqual(export_bindings(app)["rows"][0]["keep_mode"],payload["keep_mode"])

    def test_json_rejects_physical_assignment_even_if_disabled(self):
        with self.assertRaises(CatalogError):
            parse_rows({"switches":render_rows([{"entity_id":ENTITY,"enabled":False,
              "keep_mode":{"left":"control_relay"},"actions":{"single_left":["light.bra"]},
              "disabled_actions":["single_left"]}])})


    def test_runtime_power_is_aggregate_fresh_and_verified(self):
        from test_control_mvp import ControlTests, DEVICE, INVENTORY, message
        from test_control_mvp import BASE as B, NAME as N
        with tempfile.TemporaryDirectory() as td:
            app=ControlTests().app(td)
            app.config["rooms"][0]["switches"][0]["power_meter"]=True
            inventory=deepcopy(INVENTORY)
            inventory[1]["definition"]["exposes"].append(
                {"type":"numeric","property":"power","unit":"W","access":1})
            app._on_message(None,None,message(B+"/bridge/devices",inventory,True))
            app._on_message(None,None,message(B+"/bridge/state",{"state":"online"},True))
            app._on_message(None,None,message(B+"/"+N,{"power":42.5},True))
            app._publish_details()
            self.assertIsNone(app.device_details[0]["switches"][0]["power_w"])
            app._on_message(None,None,message(B+"/"+N,{"power":42.5,"power_left":18.0}))
            app._publish_details()
            self.assertEqual(app.device_details[0]["switches"][0]["power_w"],42.5)
            app._on_message(None,None,message(B+"/"+N+"/availability",{"state":"offline"}))
            app._publish_details()
            self.assertIsNone(app.device_details[0]["switches"][0]["power_w"])

    def test_queued_action_cannot_use_stale_mode_after_offline(self):
        from test_control_mvp import ControlTests, message
        from test_control_mvp import BASE as B, NAME as N
        with tempfile.TemporaryDirectory() as td:
            app=ControlTests().app(td)
            app._on_message(None,None,message(B+"/"+N,{"action":"single"}))
            self.assertEqual(app._jobs.qsize(),1)
            app._on_message(None,None,message(B+"/"+N+"/availability",{"state":"offline"}))
            app._on_message(None,None,message(B+"/"+N+"/availability",{"state":"online"}))
            failures=[]
            def capture(**kwargs):
                failures.append(kwargs)
                app._stop.set()
            app._publish_action=capture
            app._run_actions()
            app._ha_client.execute.assert_not_called()
            self.assertEqual(failures[0]["state"],"error")

    def test_explicit_off_hold_and_fresh_relay(self):
        sw=saved()
        sw["keep_mode"]={"left":"decoupled/OFF"}
        features=capabilities(wired())
        self.assertFalse(mode_action_allowed(sw,"single_left",state(),features,False))
        self.assertTrue(mode_action_allowed(sw,"single_left",state(left_relay="OFF"),features,False))
        self.assertEqual(next_repair(sw["keep_mode"],features,state(),False),("state_left","OFF"))
        self.assertEqual(next_repair(sw["keep_mode"],features,state(left="control_relay"),False),("operation_mode_left","decoupled"))
        self.assertEqual(next_repair(sw["keep_mode"],features,state(),True),("operation_mode_left","control_relay"))
        app=SimpleApp()
        app.config["rooms"][0]["switches"][0]["keep_mode"]=sw["keep_mode"]
        app._fresh_fields.discard((BASE,NAME,"state_left"))
        tick(app,1);tick(app,2)
        self.assertEqual(app.sent,[(BASE+"/"+NAME+"/get",{"state_left":""},False)])
        app._fresh_fields.add((BASE,NAME,"state_left"))
        tick(app,3);tick(app,3.61)
        self.assertEqual(app.sent[-1],(BASE+"/"+NAME+"/set",{"state_left":"OFF"},False))

    def test_off_policy_roundtrip_without_migration(self):
        rows=[{"entity_id":ENTITY,"enabled":True,"keep_mode":{"left":"decoupled/OFF"},
               "actions":{"single_left":["light.bra"]}}]
        options={"switches":render_rows(rows)}
        self.assertEqual(parse_rows(options),rows)
        self.assertEqual(project(profiles(),options)["rooms"][0]["switches"][0]["keep_mode"],rows[0]["keep_mode"])
