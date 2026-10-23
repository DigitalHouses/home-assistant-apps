"""Offline-safe direct Z2M light control; no real lights or HA service calls."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import types

from aqara_switch.light_routes import discover_routes
from aqara_switch.mqtt_lights import plan_batch
from aqara_switch.runtime import Application

BASE="zigbee2mqtt_1"
COORD="0x00124b002e1330dd"
A="0x00158d0000000111"
B="0x00158d0000000222"
S="0x00158d0000000333"
L1="light.livingroom_chandelier"
L2="light.livingroom_spots"
SN="aqara_switch_livingroom"
SKEY="switch.aqara_switch_livingroom"

def light(ieee,name):
    return {"ieee_address":ieee,"friendly_name":name,"type":"Router",
        "definition":{"vendor":"Test","model":"Z2M-LIGHT","exposes":[
            {"type":"light","features":[
                {"property":"state","type":"binary","access":7},
                {"property":"brightness","type":"numeric","access":7,
                 "value_min":0,"value_max":254},
                {"property":"color_temp","type":"numeric","access":7,
                 "value_min":150,"value_max":500},
                {"property":"color_xy","type":"composite","access":7}]}]}}
def switch():
    return {"ieee_address":S,"friendly_name":SN,"type":"EndDevice",
        "definition":{"vendor":"Aqara","model":"WXKG13LM","exposes":[
            {"type":"enum","property":"action","access":1,
             "values":["single","double"]}]}}
DEV=[{"ieee_address":COORD,"type":"Coordinator"},
     light(A,"chandelier"),light(B,"spots"),switch()]
DEVICES=[
    {"id":"ha1","identifiers":[["mqtt","zigbee2mqtt_"+A]],"connections":[]},
    {"id":"ha2","identifiers":[["mqtt","zigbee2mqtt_"+B]],"connections":[]}]
ENTITIES=[
    {"entity_id":L1,"device_id":"ha1","platform":"mqtt","disabled_by":None},
    {"entity_id":L2,"device_id":"ha2","platform":"mqtt","disabled_by":None}]
SNAP=[{"base_topic":BASE,"coordinator_ieee":COORD,
       "devices":json.dumps(DEV).encode(),"states":{}}]

def routes():
    return discover_routes(SNAP,DEVICES,ENTITIES)
def networks(on="ON",other="OFF"):
    return {BASE:{"bridge_state":"online",
                  "info":json.dumps({"coordinator":{"ieee_address":COORD}}).encode(),
                  "devices":json.dumps(DEV).encode(),
                  "states":{"chandelier":{"state":on,"brightness":140},
                            "spots":{"state":other,"brightness":150}}}}
def commands(service="light.toggle",data=None):
    result={"service":service,"target":{"entity_id":[L1,L2]}}
    if data: result["data"]=data
    return [result]
def plan(cmds=None,available=None,states=None,shadows=None,at=None,now=10):
    return plan_batch(cmds or commands(),routes(),states or networks(),
                      available if available is not None else {
                          (BASE,"chandelier"):"online",(BASE,"spots"):"online"},
                      {(BASE,"chandelier","state"),(BASE,"spots","state")},
                      shadows or {},at or {},now)

class LightOutputTests(unittest.TestCase):
    def test_registry_mapping_persists_exact_network_ieee_and_name(self):
        rs=routes()
        self.assertEqual(set(rs),{L1,L2})
        self.assertEqual(rs[L1]["friendly_name"],"chandelier")
        self.assertEqual(rs[L1]["ieee"],A)
        self.assertEqual(rs[L1]["base_topic"],BASE)
        self.assertNotIn("switch.",str(rs))
        dup=ENTITIES+[{"entity_id":"light.ambiguous","device_id":"ha1"}]
        self.assertNotIn(L1,discover_routes(SNAP,DEVICES,dup))
        no_link=discover_routes(SNAP,[],ENTITIES)
        self.assertEqual(no_link,{})

    def test_mixed_state_toggle_forces_both_on_not_disco(self):
        plans,skipped=plan()
        self.assertFalse(skipped)
        self.assertEqual([(x["light"],x["state"],x["payload"]) for x in plans],[
            (L1,"ON",{"state":"ON"}),(L2,"ON",{"state":"ON"})])
        plans,_=plan(states=networks("ON","ON"))
        self.assertEqual([x["state"] for x in plans],["OFF","OFF"])
        plans,_=plan(states=networks("OFF","OFF"))
        self.assertEqual([x["state"] for x in plans],["ON","ON"])
        self.assertNotIn("TOGGLE",str(plans))

    def test_offline_skipped_and_never_receives_set(self):
        plans,skipped=plan(available={(BASE,"chandelier"):"online",
                                      (BASE,"spots"):"offline"})
        self.assertEqual([x["light"] for x in plans],[L1])
        self.assertEqual(plans[0]["payload"],{"state":"OFF"})  # only online ON
        self.assertEqual(skipped[0]["light"],L2)
        plans,skipped=plan(available={(BASE,"chandelier"):"offline",
                                      (BASE,"spots"):"unknown"})
        self.assertEqual(plans,[])
        self.assertEqual(len(skipped),2)

    def test_missing_or_unknown_state_never_blind_toggles(self):
        nets=networks()
        nets[BASE]["states"]["spots"].pop("state")
        plans,skipped=plan(states=nets)
        self.assertEqual([p["light"] for p in plans],[L1])
        self.assertEqual(plans[0]["state"],"OFF")
        self.assertEqual(skipped[0]["reason"],"Unknown/unconfirmed light state")
        nets=networks()
        nets[BASE]["bridge_state"]="offline"
        plans,skipped=plan(states=nets)
        self.assertEqual(plans,[])
        self.assertEqual(len(skipped),2)

    def test_fast_second_press_uses_in_flight_command_not_old_report(self):
        shadows={(BASE,"chandelier"):{"value":"ON","at":10},
                 (BASE,"spots"):{"value":"ON","at":10}}
        plans,_=plan(shadows=shadows,now=10.2)
        self.assertEqual([p["state"] for p in plans],["OFF","OFF"])
        # Once the shadow expires with no confirming report, fail closed.
        plans,skipped=plan(shadows=shadows,now=17)
        self.assertEqual(plans,[])
        self.assertEqual(len(skipped),2)

    def test_per_light_z2m_brightness_kelvin_and_rgb(self):
        plans,skipped=plan(cmds=[
            {"service":"light.turn_on","target":{"entity_id":[L1]},
             "data":{"brightness_pct":50,"color_temp_kelvin":3000}},
            {"service":"light.turn_on","target":{"entity_id":[L2]},
             "data":{"brightness_pct":70,"rgb_color":[255,80,30]}}])
        self.assertFalse(skipped)
        self.assertEqual(plans[0]["payload"],{
            "state":"ON","brightness":127,"color_temp":333})
        self.assertEqual(plans[1]["payload"]["brightness"],178)
        self.assertIn("color",plans[1]["payload"])
        self.assertIn("x",plans[1]["payload"]["color"])

    def test_unknown_or_unsupported_attribute_is_skipped(self):
        rs=routes()
        # Keep the verified hardware route unchanged, but model a lamp
        # that really has no writable color_temp capability.
        rs[L1]["features"].pop("color_temp")
        from copy import deepcopy
        changed=deepcopy(DEV)
        for device in changed:
            if device.get("ieee_address")==A:
                device["definition"]["exposes"][0]["features"]=[
                    f for f in device["definition"]["exposes"][0]["features"]
                    if f.get("property")!="color_temp"
                ]
        net=networks()
        net[BASE]["devices"]=json.dumps(changed).encode()
        plans,skipped=plan_batch([
            {"service":"light.turn_on","target":{"entity_id":[L1]},
             "data":{"color_temp_kelvin":3000}}],rs,net,{
             (BASE,"chandelier"):"online"},
             {(BASE,"chandelier","state")},{},{},10)
        self.assertEqual(plans,[])
        self.assertIn("color_temp",skipped[0]["reason"])

class FakeMQTT:
    class Client:
        def __init__(self,**kwargs):
            self.subscriptions=[]
            self.published=[]
        def will_set(self,*a,**kw):pass
        def reconnect_delay_set(self,*a,**kw):pass
        def subscribe(self,topic,qos=1):
            self.subscriptions.append(topic)
            return (0,1)
        def publish(self,topic,payload,qos=1,retain=False):
            self.published.append((topic,payload,retain))
            return types.SimpleNamespace(rc=0)
def msg(topic,payload,retained=False):
    data=payload if isinstance(payload,bytes) else json.dumps(payload).encode()
    return types.SimpleNamespace(topic=topic,payload=data,
                                 retain=retained,dup=False)

class IntegrationTests(unittest.TestCase):
    def test_button_to_online_only_z2m_commands_without_ha(self):
        from aqara_switch.catalog import candidate_from_mqtt
        saved=candidate_from_mqtt(switch(),coordinator_ieee=COORD,
                                  base_topic=BASE,reported_state={})
        saved.update({"entity_id":SKEY,"enabled":True,"bindings":{},
                      "panel_relay":None})
        adopted={"rooms":[{"name":"Гостиная","area_id":None,"switches":[saved]}],
                 "light_routes":routes()}
        opts=Mock()
        opts.read.return_value={"switches":"""
- switch.aqara_switch_livingroom:
    enabled: true
    actions:
      single:
        - light.livingroom_chandelier
        - light.livingroom_spots
"""}
        with TemporaryDirectory() as td, patch(
                "aqara_switch.entity_options._read_profiles",
                return_value=adopted):
            ha=Mock()
            app=Application(FakeMQTT,options=opts,registry=Mock(),
                            last_scan_path=Path(td)/"scan.json",
                            version="0.1.12",ha_client=ha)
        app._on_connect(None,None,None,0)
        app._on_message(None,None,msg(BASE+"/bridge/info",{
            "coordinator":{"ieee_address":COORD}},True))
        app._on_message(None,None,msg(BASE+"/bridge/devices",DEV,True))
        app._on_message(None,None,msg(BASE+"/bridge/state",{"state":"online"},True))
        app._on_message(None,None,msg(BASE+"/chandelier/availability",b"online",True))
        app._on_message(None,None,msg(BASE+"/spots/availability",b"offline",True))
        app._on_message(None,None,msg(BASE+"/chandelier",{"state":"ON"}))
        app._on_message(None,None,msg(BASE+"/spots",{"state":"OFF"}))
        app._on_message(None,None,msg(BASE+"/"+SN,{"action":"single"}))
        self.assertEqual(app._jobs.qsize(),1)
        states=[]
        def capture(**kwargs):
            states.append(kwargs)
            app._stop.set()
        app._publish_action=capture
        app._run_actions()
        outgoing=[(topic,json.loads(data),retain) for topic,data,retain
                  in app.client.published if topic.endswith("/set")]
        self.assertEqual(outgoing,[(BASE+"/chandelier/set",{"state":"OFF"},False)])
        self.assertEqual(states[0]["state"],"partial")
        self.assertIn("spots",states[0]["error"])
        ha.execute.assert_not_called()

if __name__=="__main__":
    unittest.main()
