"""One Aqara MQTT press dispatches exactly one HA light.toggle with N targets."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
import json
import types

from aqara_switch.catalog import candidate_from_mqtt
from aqara_switch.control import HAClient, light_action, settings_drift
from aqara_switch.runtime import Application
from aqara_switch.mqtt_ui import ROOT

COORD="0x00124b002e1330dd"
IEEE="0x00158d0000000001"
BASE="zigbee2mqtt_1"
NAME="aqara_livingroom"
ENTITY="switch.livingroomaqaraswitch"
TARGETS=["light.dh_aqara_lab_chandelier","light.dh_aqara_lab_spots"]
DEVICE={
    "ieee_address":IEEE,"friendly_name":NAME,"type":"Router",
    "model_id":"lumi.remote.test",
    "definition":{"vendor":"Aqara","model":"TEST-PANEL",
        "exposes":[{"type":"enum","property":"action","access":1,
                    "values":["single","double"]},
                   {"type":"enum","property":"operation_mode_left","access":7,
                    "values":["control_relay","decoupled"]},
                   {"type":"switch","features":[
                    {"type":"binary","property":"state_left","access":7}]}]}}
SAVED=candidate_from_mqtt(DEVICE,coordinator_ieee=COORD,base_topic=BASE,
                          reported_state={"operation_mode_left":"decoupled"})
SAVED.update({"entity_id":ENTITY,
              "bindings":{"single":{"action":"toggle","targets":TARGETS}},
              "panel_relay":None,"enabled":True,"keep_mode":{"left":"decoupled/ON"}})
PROFILES={"rooms":[{"area_id":"livingroom","name":"Гостиная","switches":[SAVED]}]}
SNAPSHOT={"coordinator":{"ieee_address":COORD}}
INVENTORY=[{"ieee_address":COORD,"type":"Coordinator"},DEVICE]


class FakeMQTT:
    class Client:
        def __init__(self,**kwargs):
            self.subscriptions=[]
            self.published=[]
        def will_set(self,*a,**kw): pass
        def reconnect_delay_set(self,*a,**kw): pass
        def subscribe(self,topic,qos=1):
            self.subscriptions.append(topic)
            return (0,1)
        def publish(self,topic,payload,qos=1,retain=False):
            self.published.append((topic,payload,retain))
            return types.SimpleNamespace(rc=0)


def message(topic, data, retain=False, dup=False):
    return types.SimpleNamespace(topic=topic,payload=json.dumps(data).encode(),
                                 retain=retain,dup=dup)


class ControlTests(TestCase):
    def app(self, td, enabled=True):
        options=Mock()
        options.read.return_value={"switches":(
            "- switch.livingroomaqaraswitch:\n"
            f"    enabled: {str(enabled).lower()}\n"
            "    keep_mode:\n"
            "      left: decoupled/ON\n"
            "    actions:\n"
            "      single:\n"
            "        - light.dh_aqara_lab_chandelier\n"
            "        - light.dh_aqara_lab_spots\n")}
        with patch("aqara_switch.entity_options._read_profiles",return_value=PROFILES):
            app=Application(FakeMQTT,options=options,registry=Mock(),
                            last_scan_path=Path(td)/"scan.json",version="0.1.6",
                            ha_client=Mock())
        app._on_connect(None,None,None,0)
        app._on_message(None,None,message(BASE+"/bridge/info",SNAPSHOT,True))
        app._on_message(None,None,message(BASE+"/bridge/devices",INVENTORY,True))
        # Fresh observed mode/relay state is required before the wired key
        # can dispatch actions (retained startup data alone is insufficient).
        app._on_message(None,None,message(BASE+"/"+NAME,{
            "operation_mode_left":"decoupled","state_left":"ON"}))
        return app

    def test_two_targets_one_queue_and_no_replay(self):
        with TemporaryDirectory() as td:
            app=self.app(td)
            topic=BASE+"/"+NAME
            app._on_message(None,None,message(topic,{"action":"single"},retain=True))
            app._on_message(None,None,message(topic,{"action":"single"},dup=True))
            self.assertEqual(app._jobs.qsize(),0)
            app._on_message(None,None,message(topic,{"action":"double"}))
            self.assertEqual(app._jobs.qsize(),0)
            app._on_message(None,None,message(topic,{"action":"single"}))
            self.assertEqual(app._jobs.get_nowait(),(NAME,"single",[{"service":"light.toggle","target":{"entity_id":TARGETS}}]))
            app._on_message(None,None,message(topic,{"action":"single"}))
            self.assertTrue(app._jobs.empty())
            self.assertTrue(all(not t.endswith("/set") for t,_,_ in app.client.published))

    def test_enabled_false_disables_action_and_keeper(self):
        with TemporaryDirectory() as td:
            app=self.app(td,enabled=False)
            app._on_message(None,None,message(BASE+"/"+NAME,
                {"action":"single","operation_mode_left":"control_relay"}))
            self.assertTrue(app._jobs.empty())
            self.assertFalse(any(t.endswith("/set") for t,_,_ in app.client.published))

    def test_light_action_allows_multiple_but_rejects_relay(self):
        result=light_action(SAVED,"single")
        self.assertEqual(result["service"],"light.toggle")
        self.assertEqual(result["target"]["entity_id"],TARGETS)
        with self.assertRaises(ValueError):
            light_action({**SAVED,"bindings":{"single":{
                "action":"toggle","targets":["switch.actual_relay"]}}},"single")
        self.assertEqual(settings_drift(SAVED,{"operation_mode_left":"control_relay"}),
                         {"operation_mode_left":"decoupled"})

    def test_one_ha_service_call_contains_all_lights(self):
        requests=[]
        class Response:
            status=200
            def __enter__(self): return self
            def __exit__(self,*a): pass
        def openurl(req,timeout):
            requests.append((req.full_url,json.loads(req.data)))
            return Response()
        with patch("urllib.request.urlopen",side_effect=openurl):
            HAClient("fake").toggle_targets(TARGETS)
        self.assertEqual(requests,[(
            "http://supervisor/core/api/services/light/toggle",
            {"entity_id":TARGETS}
        )])


if __name__=="__main__":
    import unittest
    unittest.main()
