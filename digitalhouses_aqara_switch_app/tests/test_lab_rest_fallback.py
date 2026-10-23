"""Regression: Aqara v0.1.12 must not strand six virtual LAB lights."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import Mock, patch

from aqara_switch.actions import ActionError
from aqara_switch.catalog import candidate_from_mqtt
from aqara_switch.control import HAClient
from aqara_switch.lab_lights import LAB_LIGHTS, partition_commands, plan_lab
from aqara_switch.runtime import Application

COORD="0x00124b002e1330dd"
IEEE="0x00158d0000000088"
BASE="zigbee2mqtt_1"
NAME="aqara_battery_button"
LAB="light.dh_aqara_lab_night_light"
CHAND="light.dh_aqara_lab_chandelier"
SPOTS="light.dh_aqara_lab_spots"
DEVICE={
    "ieee_address":IEEE, "friendly_name":NAME, "type":"EndDevice",
    "definition":{"vendor":"Aqara","model":"WXKG13LM",
     "exposes":[{"type":"enum","property":"action","access":1,
                 "values":["single","double","double_plus"]}]}}
SAVED=candidate_from_mqtt(DEVICE,coordinator_ieee=COORD,
                          base_topic=BASE,reported_state={})
SAVED.update({"entity_id":"switch.aqara_battery_button","enabled":True,
              "bindings":{},"panel_relay":None})
PROFILE={"rooms":[{"area_id":None,"name":"Без комнаты","switches":[SAVED]}]}

class FakeMQTT:
    class Client:
        def __init__(self,**kw): self.published=[];self.subscriptions=[]
        def will_set(self,*a,**kw): pass
        def reconnect_delay_set(self,**kw):pass
        def subscribe(self,topic,qos=1):
            self.subscriptions.append(topic)
            return (0,1)
        def publish(self,topic,payload,qos=1,retain=False):
            self.published.append((topic,payload,retain))
            return types.SimpleNamespace(rc=0)

def packet(topic,value,retain=False):
    return types.SimpleNamespace(topic=topic,payload=json.dumps(value).encode(),
                                 retain=retain,dup=False)

class LabTests(unittest.TestCase):
    def test_lab_whitelist_is_exactly_six(self):
        self.assertEqual(len(LAB_LIGHTS),6)
        self.assertIn(LAB,LAB_LIGHTS)
        self.assertNotIn("light.any_real_zigbee_lamp",LAB_LIGHTS)
        self.assertNotIn("switch.actual_relay",LAB_LIGHTS)

    def test_double_plus_virtual_night_light_has_no_z2m_route(self):
        command={"service":"light.turn_on","target":{"entity_id":[LAB]},
                 "data":{"brightness_pct":70,"color_temp_kelvin":3000}}
        mqtt,ha=partition_commands([command],{})
        self.assertFalse(mqtt)
        planned,skip=plan_lab(ha,lambda eid:"off",{},10)
        self.assertEqual(skip,[])
        self.assertEqual(planned,[command])

    def test_group_toggle_virtual_lights_stays_synchronized(self):
        command={"service":"light.toggle","target":{"entity_id":[CHAND,SPOTS]}}
        _,ha=partition_commands([command],{})
        current={CHAND:"on",SPOTS:"off"}
        plans,skipped=plan_lab(ha,lambda x:current[x],{},10)
        self.assertEqual(skipped,[])
        self.assertEqual(plans[0]["service"],"light.turn_on")
        self.assertEqual(plans[0]["target"]["entity_id"],[CHAND,SPOTS])
        # Next press while HA still reflects old state: shadow takes priority.
        shadow={x:{"state":"on","at":10.2} for x in (CHAND,SPOTS)}
        plans,skip=plan_lab(ha,lambda x:current[x],shadow,10.3)
        self.assertEqual(plans[0]["service"],"light.turn_off")
        self.assertEqual(skip,[])

    def test_offline_virtual_light_is_skipped_without_blocking_others(self):
        cmd={"service":"light.turn_on","target":{"entity_id":[CHAND,SPOTS]}}
        _,ha=partition_commands([cmd],{})
        plans,skips=plan_lab(ha,lambda x:"unavailable" if x == CHAND else "off",{},10)
        self.assertEqual(plans[0]["target"]["entity_id"],[SPOTS])
        self.assertEqual([s["light"] for s in skips],[CHAND])

    def test_real_or_unmapped_lamp_must_never_fall_back_to_ha(self):
        cmd={"service":"light.turn_on",
             "target":{"entity_id":["light.real_zigbee_lamp"]}}
        mqtt,ha=partition_commands([cmd],{})
        self.assertEqual(ha,[])
        self.assertEqual(mqtt,[cmd])
        with self.assertRaises(ValueError):
            HAClient("dummy-token").read_lab_state("light.real_zigbee_lamp")
        # A LAB lamp that has a verified route must also use Z2M.
        mqtt,ha=partition_commands(
            [{"service":"light.turn_on","target":{"entity_id":[LAB]}}],
            {LAB:{"base_topic":BASE}})
        self.assertEqual(ha,[])
        self.assertEqual(len(mqtt),1)

    def test_mixed_lab_z2m_toggle_is_refused_rather_than_disco(self):
        cmd={"service":"light.toggle",
             "target":{"entity_id":[CHAND,"light.real_lamp"]}}
        with self.assertRaisesRegex(ActionError,"cannot mix"):
            partition_commands([cmd],{})
        one={"service":"light.toggle","target":{"entity_id":[CHAND]}}
        two={"service":"light.toggle",
             "target":{"entity_id":["light.real_lamp"]}}
        with self.assertRaisesRegex(ActionError,"cannot mix"):
            partition_commands([one,two],{})

    def test_ha_state_get_is_restricted_to_virtual_lab(self):
        calls=[]
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self):return b'{"entity_id":"light.dh_aqara_lab_night_light","state":"off"}'
        def urlopen(req,timeout):
            calls.append((req.full_url,req.get_header("Authorization"),req.get_method()))
            return Response()
        with patch("urllib.request.urlopen",side_effect=urlopen):
            state=HAClient("token").read_lab_state(LAB)
        self.assertEqual(state,"off")
        self.assertEqual(calls,[(
            "http://supervisor/core/api/states/"+LAB,"Bearer token","GET")])

    def test_end_to_end_battery_press_turns_on_virtual_night_light(self):
        ha=Mock()
        ha.read_lab_state.return_value="off"
        options=Mock()
        options.read.return_value={"switches":"""
- switch.aqara_battery_button:
    enabled: true
    actions:
      double_plus:
        service: light.turn_on
        targets:
          - light.dh_aqara_lab_night_light:
              brightness_pct: 70
              color_temp_kelvin: 3000
"""}
        with TemporaryDirectory() as td,patch(
            "aqara_switch.entity_options._read_profiles",
            return_value=PROFILE):
            app=Application(FakeMQTT,options=options,registry=Mock(),
                last_scan_path=Path(td)/"scan.json",version="0.1.13",
                ha_client=ha)
        app._on_connect(None,None,None,0)
        app._on_message(None,None,packet(BASE+"/bridge/info",
            {"coordinator":{"ieee_address":COORD}},True))
        app._on_message(None,None,packet(BASE+"/bridge/devices",
            [{"type":"Coordinator","ieee_address":COORD},DEVICE],True))
        app._on_message(None,None,packet(BASE+"/"+NAME,
            {"action":"double_plus"}))
        self.assertEqual(app._jobs.qsize(),1)
        results=[]
        def on_action(**kw):
            results.append(kw)
            app._stop.set()
        app._publish_action=on_action
        app._run_actions()
        ha.read_lab_state.assert_called_once_with(LAB)
        ha.execute.assert_called_once_with({
            "service":"light.turn_on","target":{"entity_id":[LAB]},
            "data":{"brightness_pct":70,"color_temp_kelvin":3000}})
        self.assertEqual(results[0]["state"],"sent")
        self.assertEqual(results[0]["target"],LAB)
        self.assertFalse(any(t.endswith("/set") for t,_,_ in app.client.published))

if __name__=="__main__":
    unittest.main()
