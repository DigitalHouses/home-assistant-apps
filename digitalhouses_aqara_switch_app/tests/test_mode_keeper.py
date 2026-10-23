"""Aqara selective decoupled Mode Keeper, battery exemptions, Maintenance FSM."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from aqara_switch.catalog import CatalogError, candidate_from_mqtt
from aqara_switch.control import verified_adopted_switch
from aqara_switch.entity_options import _save_profiles, current, parse_rows
from aqara_switch.keeper_runtime import tick
from aqara_switch.mode_keeper import (
    KEEP_VALUE, MODE_TO_RELAY, capabilities, capture_keep_mode,
    global_policy, maintained_switch, mode_action_allowed, next_repair)

BASE="zigbee2mqtt_1"
COORD="0x00124b002e1330dd"
IEEE="0x00158d0000000022"
ENTITY="switch.aqara_switch_livingroom"
NAME="aqara_switch_livingroom"

def wired():
    return {"ieee_address":IEEE,"friendly_name":NAME,"type":"Router",
            "model_id":"lumi.switch.b2lacn02",
            "definition":{"vendor":"Aqara","model":"WS-EUK04",
                          "exposes":[
                {"type":"enum","property":"action","access":1,
                 "values":["single_left","double_left","single_right","double_both"]},
                {"type":"enum","property":"operation_mode_left","access":7,
                 "values":["control_relay","decoupled"]},
                {"type":"enum","property":"operation_mode_right","access":7,
                 "values":["control_relay","decoupled"]},
                {"type":"switch","features":[
                    {"type":"binary","property":"state_left","access":7},
                    {"type":"binary","property":"state_right","access":7}]}]}}

def battery():
    return {"ieee_address":"0x00158d0000000033",
            "friendly_name":"aqara_battery_button","type":"EndDevice",
            "definition":{"vendor":"Aqara","model":"WXKG13LM",
                          "exposes":[{"type":"enum","property":"action","access":1,
                                      "values":["single","double","hold"]}]}}

def state(left="decoupled", left_relay="ON",right="control_relay"):
    return {"operation_mode_left":left,"operation_mode_right":right,
            "state_left":left_relay,"state_right":"ON"}

def saved():
    candidate=candidate_from_mqtt(wired(),coordinator_ieee=COORD,
                                  base_topic=BASE,reported_state=state())
    candidate.update({"entity_id":ENTITY,"entity_source":"logical","bindings":{},
                      "panel_relay":None,"enabled":True,"keep_mode":{"left":KEEP_VALUE},
                      "maintenance_mode":False})
    return candidate

def profiles():
    return {"rooms":[{"area_id":None,"name":"Без комнаты","switches":[saved()]}]}

def options_for(keep=True,maintenance=False):
    import yaml
    row={"enabled":True,"maintenance_mode":maintenance,"actions":{
        "single_left":["light.dh_aqara_lab_chandelier"],
    }}
    if keep: row["keep_mode"]={"left":KEEP_VALUE}
    return {"maintenance_mode":False,"restore_delay":0.6,"switches":
        yaml.safe_dump([{ENTITY:row}],sort_keys=False)}

class SimpleApp:
    def __init__(self):
        self.config=profiles()
        self.globals={"maintenance_mode":False,"restore_delay":0.6}
        self._networks={BASE:{
            "info":json.dumps({"coordinator":{"ieee_address":COORD}}).encode(),
            "devices":json.dumps([{"type":"Coordinator","ieee_address":COORD},
                                   wired()]).encode(),
            "states":{NAME:state()}}}
        self._fresh_fields={(BASE,NAME,k) for k in state()}
        self._mode_pending={}
        self._mode_probes={}
        self._last_mode_request={}
        self.sent=[]
    def _publish(self,topic,data,retain=True):
        self.sent.append((topic,data,retain))

class KeeperTests(unittest.TestCase):
    def test_capture_only_existing_decoupled_key_not_control_relay(self):
        capture,warnings=capture_keep_mode(wired(),state())
        self.assertEqual(capture,{"left":KEEP_VALUE})
        self.assertEqual(warnings,[])
        self.assertEqual(capture_keep_mode(battery(),{}),({},[]))
        self.assertEqual(capture_keep_mode(wired(),state(left_relay="OFF"))[0],
                         {"left":KEEP_VALUE})
        missing=state()
        missing.pop("state_left")
        self.assertEqual(capture_keep_mode(wired(),missing)[0],{})

    def test_battery_button_not_subject_to_mode_keeper(self):
        self.assertEqual(capabilities(battery()),{})
        sw={"fingerprint":{"setting_keys":[]},"keep_mode":{}}
        self.assertTrue(mode_action_allowed(sw,"single",{}, {},False))
        self.assertFalse(mode_action_allowed(sw,"single",{}, {},True))
        with self.assertRaises(CatalogError):
            with TemporaryDirectory() as td:
                path=Path(td)/"stored.json"
                candidate=candidate_from_mqtt(battery(),coordinator_ieee=COORD,
                    base_topic=BASE,reported_state={})
                candidate.update({"entity_id":"switch.aqara_battery_button",
                                  "bindings":{},"panel_relay":None})
                _save_profiles(path,{"rooms":[{"area_id":None,"name":"Без комнаты",
                                               "switches":[candidate]}]})
                current({"switches":"""
- switch.aqara_battery_button:
    enabled: true
    keep_mode: {left: decoupled/ON}
    actions: {}
"""},path)

    def test_controls_require_decoupled_both_keys_for_both(self):
        sw=saved()
        self.assertTrue(mode_action_allowed(sw,"single_left",state(),
                                            capabilities(wired()),False))
        self.assertFalse(mode_action_allowed(sw,"single_right",state(),
                                             capabilities(wired()),False))
        self.assertFalse(mode_action_allowed(sw,"double_both",state(),
                                             capabilities(wired()),False))
        self.assertFalse(mode_action_allowed(sw,"single_left",
                                             state(left="control_relay"),
                                             capabilities(wired()),False))
        self.assertFalse(mode_action_allowed(sw,"single_left",
                                             state(left_relay="OFF"),
                                             capabilities(wired()),False))
        sw["keep_mode"]["right"]=KEEP_VALUE
        self.assertTrue(mode_action_allowed(sw,"double_both",
                            state(right="decoupled"),capabilities(wired()),False))
        self.assertFalse(mode_action_allowed(sw,"double_both",
                            state(right="control_relay"),capabilities(wired()),False))

    def test_schema_and_optional_local_policy(self):
        with TemporaryDirectory() as td:
            path=Path(td)/"store.json"
            _save_profiles(path,profiles())
            item=current(options_for(),path)["rooms"][0]["switches"][0]
            self.assertEqual(item["keep_mode"],{"left":KEEP_VALUE})
            self.assertFalse(item["maintenance_mode"])
            self.assertEqual(item["bindings"]["single_left"]["targets"],
                             ["light.dh_aqara_lab_chandelier"])
            self.assertTrue(current(options_for(maintenance=True),path)
                            ["rooms"][0]["switches"][0]["maintenance_mode"])
            self.assertEqual(current(options_for(keep=False),path)
                             ["rooms"][0]["switches"][0]["keep_mode"],{})
        self.assertEqual(global_policy({}),{"maintenance_mode":False,"restore_delay":0.6})
        self.assertEqual(global_policy({"maintenance_mode":True,"restore_delay":0.6})
                         ["maintenance_mode"],True)
        for options in ({"maintenance_mode":"true"},
                        {"restore_delay":0},{"restore_delay":31},
                        {"restore_delay":True},{"restore_delay":float("nan")}):
            with self.subTest(options=options):
                with self.assertRaises(CatalogError):
                    global_policy(options)

    def test_delay_order_and_verification_without_forcing_right(self):
        app=SimpleApp()
        app._networks[BASE]["states"][NAME]=state(left="control_relay",left_relay="OFF")
        tick(app,1.0)
        self.assertFalse(app.sent)
        tick(app,1.59)
        self.assertFalse(app.sent)
        tick(app,1.61)
        self.assertEqual(app.sent,[(BASE+"/"+NAME+"/set",
                                    {"operation_mode_left":"decoupled"},False)])
        tick(app,2)
        self.assertEqual(len(app.sent),1)  # 60s throttle, no spam
        app._networks[BASE]["states"][NAME]=state(left="decoupled",left_relay="OFF")
        tick(app,2.2)
        tick(app,2.81)
        self.assertEqual(app.sent[1],(BASE+"/"+NAME+"/set",{"state_left":"ON"},False))
        self.assertNotIn("operation_mode_right",str(app.sent))
        self.assertNotIn("state_right",str(app.sent))
        app._networks[BASE]["states"][NAME]=state()
        tick(app,3.0)
        tick(app,5.0)
        self.assertEqual(len(app.sent),2)

    def test_maintenance_blocks_actions_and_only_sets_control_mode(self):
        app=SimpleApp()
        app.globals["maintenance_mode"]=True
        self.assertFalse(mode_action_allowed(app.config["rooms"][0]["switches"][0],
                    "single_left",state(),capabilities(wired()),True))
        tick(app,1)
        tick(app,1.61)
        self.assertEqual(app.sent,[(BASE+"/"+NAME+"/set",
                     {"operation_mode_left":"control_relay"},False)])
        app._networks[BASE]["states"][NAME]=state(left="control_relay")
        tick(app,2)
        tick(app,3)
        self.assertEqual(len(app.sent),1)
        app.globals["maintenance_mode"]=False
        tick(app,4)
        tick(app,4.61)
        self.assertEqual(app.sent[1],(BASE+"/"+NAME+"/set",
                                      {"operation_mode_left":"decoupled"},False))

    def test_unconfirmed_retained_state_only_queries_not_writes(self):
        app=SimpleApp()
        app._fresh_fields.clear()
        app._networks[BASE]["states"][NAME]=state(left="control_relay",left_relay="OFF")
        tick(app,10)
        tick(app,12)
        self.assertEqual(len(app.sent),1)
        self.assertTrue(app.sent[0][0].endswith("/get"))
        self.assertNotIn("/set",str(app.sent))
        for f in ("operation_mode_left","state_left"):
            app._fresh_fields.add((BASE,NAME,f))
        tick(app,20)
        tick(app,20.61)
        self.assertIn("/set",app.sent[-1][0])

if __name__=="__main__":
    unittest.main()
