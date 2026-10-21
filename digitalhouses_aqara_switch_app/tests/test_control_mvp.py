"""MVP E2E with mocked MQTT and HA: Scan/adopt -> settings keep -> light.toggle."""
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

from aqara_switch.control import light_action, settings_drift, verified_adopted_switch
from aqara_switch.runtime import Application
from aqara_switch.mqtt_ui import ROOT

COORD="0x00124b002e1330dd"
IEEE="0x00158d0000000001"
BASE="zigbee2mqtt_1"
NAME="aqara_livingroom"
DEVICE={
    "ieee_address":IEEE,"friendly_name":NAME,"type":"Router",
    "model_id":"lumi.remote.b28ac1",
    "definition":{"vendor":"Aqara","model":"TEST-PANEL",
                  "exposes":[
                    {"type":"enum","property":"action","access":1,
                     "values":["single","double"]},
                    {"type":"enum","property":"operation_mode","access":3,
                     "values":["control_relay","decoupled"]},
                    {"type":"switch","features":[
                     {"type":"binary","property":"state_left","access":7}]}]},
}
from aqara_switch.catalog import candidate_from_mqtt
SAVED=candidate_from_mqtt(DEVICE,coordinator_ieee=COORD,base_topic=BASE,
                         reported_state={"operation_mode":"decoupled"})
SAVED["bindings"]={"single":{"action":"toggle","targets":["light.livingroom"]}}
SAVED["panel_relay"]=None
CONFIG={"rooms":[{"area_id":"livingroom","name":"Гостиная","switches":[SAVED]}]}
SNAPSHOT={"coordinator":{"ieee_address":COORD}}
INVENTORY=[{"ieee_address":COORD,"type":"Coordinator"},DEVICE]


class FakeMQTT:
    class Client:
        def __init__(self, **kwargs):
            self.published=[]
            self.subscriptions=[]
        def will_set(self,*args,**kwargs): pass
        def reconnect_delay_set(self,*args,**kwargs): pass
        def subscribe(self,topic,qos=1):
            self.subscriptions.append(topic)
            return (0,1)
        def publish(self,topic,data,qos=1,retain=False):
            self.published.append((topic,data,retain))
            return types.SimpleNamespace(rc=0)


def msg(topic,data,retain=False,dup=False):
    return types.SimpleNamespace(topic=topic,payload=json.dumps(data).encode(),
                                 retain=retain,dup=dup)


class ModeAndActionTests(unittest.TestCase):
    def test_binding_is_exactly_one_light_toggle(self):
        self.assertEqual(light_action(SAVED,"single")["service"],"light.toggle")
        self.assertIsNone(light_action(SAVED,"double"))
        bad={**SAVED,"bindings":{"single":{
            "action":"toggle","targets":["switch.tongou_livingroom"]}}}
        with self.assertRaisesRegex(ValueError,"one light.toggle"):
            light_action(bad,"single")

    def test_identity_and_setting_gate(self):
        self.assertTrue(verified_adopted_switch(SAVED,DEVICE,COORD,BASE))
        self.assertFalse(verified_adopted_switch(SAVED,{**DEVICE,"ieee_address":"0x00158d0000000002"},COORD,BASE))
        self.assertFalse(verified_adopted_switch(SAVED,DEVICE,COORD,"zigbee2mqtt_2"))
        self.assertEqual(settings_drift(SAVED,{"operation_mode":"control_relay","state_left":"OFF"}),
                         {"operation_mode":"decoupled"})
        self.assertEqual(settings_drift(SAVED,{"state_left":"OFF"}),{})

    def test_mqtt_retained_and_no_binding_cannot_dispatch(self):
        with tempfile.TemporaryDirectory() as td:
            options=Mock()
            import yaml
            options.read.return_value={"configuration_yaml":yaml.safe_dump(CONFIG)}
            ha=Mock()
            app=Application(FakeMQTT,options=options,registry=Mock(),
                            last_scan_path=Path(td)/"last.json",version="0.1.2",
                            ha_client=ha)
            app._on_connect(None,None,None,0)
            app._on_message(None,None,msg(BASE+"/bridge/info",SNAPSHOT,retain=True))
            app._on_message(None,None,msg(BASE+"/bridge/devices",INVENTORY,retain=True))
            self.assertIn(BASE+"/"+NAME,app.client.subscriptions)
            # Retained/replayed press must never perform an action.
            app._on_message(None,None,msg(BASE+"/"+NAME,{"action":"single"},retain=True))
            app._on_message(None,None,msg(BASE+"/"+NAME,{"action":"single"},dup=True))
            self.assertEqual(app._jobs.qsize(),0)
            app._on_message(None,None,msg(BASE+"/"+NAME,{"action":"double"}))
            self.assertEqual(app._jobs.qsize(),0)
            # One real press queues the exact saved target.
            app._on_message(None,None,msg(BASE+"/"+NAME,{"action":"single"}))
            self.assertEqual(app._jobs.get_nowait(),(NAME,"single","light.livingroom"))
            # Same action emitted in 350ms cannot toggle twice.
            app._on_message(None,None,msg(BASE+"/"+NAME,{"action":"single"}))
            self.assertTrue(app._jobs.empty())
            # Mode restoration never touches power relays.
            app._on_message(None,None,msg(BASE+"/"+NAME,{
                "operation_mode":"control_relay","state_left":"ON"}))
            commands=[(topic,json.loads(payload))
                      for topic,payload,_ in app.client.published if topic.endswith("/set")]
            self.assertEqual(commands,[(BASE+"/"+NAME+"/set",{"operation_mode":"decoupled"})])
            self.assertFalse(any("state_left" in payload for _,payload in commands))
            self.assertEqual(options.write.call_count,0)

    def test_identity_mismatch_blocks_all_execution(self):
        with tempfile.TemporaryDirectory() as td:
            import yaml
            opts=Mock()
            opts.read.return_value={"configuration_yaml":yaml.safe_dump(CONFIG)}
            app=Application(FakeMQTT,options=opts,registry=Mock(),
                            last_scan_path=Path(td)/"scan.json",version="0.1.2",
                            ha_client=Mock())
            app._on_connect(None,None,None,0)
            app._on_message(None,None,msg(BASE+"/bridge/info",SNAPSHOT,retain=True))
            bad=[{"ieee_address":COORD,"type":"Coordinator"},
                 {**DEVICE,"ieee_address":"0x00158d0000000002"}]
            app._on_message(None,None,msg(BASE+"/bridge/devices",bad,retain=True))
            app._on_message(None,None,msg(BASE+"/"+NAME,{
                "action":"single","operation_mode":"control_relay"}))
            self.assertTrue(app._jobs.empty())
            self.assertFalse(any(topic.endswith("/set") for topic,_,_ in app.client.published))

    def test_ha_service_client_is_explicit(self):
        from aqara_switch.control import HAClient
        from unittest.mock import patch
        stub=types.SimpleNamespace(status=200)
        stub.__enter__=lambda o:o
        stub.__exit__=lambda o,*a:None
        # Test binding to exact service path with real Request and fake transport.
        calls=[]
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
        def urlopen(request,timeout):
            calls.append((request.full_url,request.get_method(),json.loads(request.data)))
            return Response()
        with patch("urllib.request.urlopen",side_effect=urlopen):
            HAClient("fake",url="http://supervisor/core/api").toggle("light.livingroom")
        self.assertEqual(calls,[("http://supervisor/core/api/services/light/toggle",
                                 "POST",{"entity_id":"light.livingroom"})])


if __name__=="__main__":
    unittest.main()
