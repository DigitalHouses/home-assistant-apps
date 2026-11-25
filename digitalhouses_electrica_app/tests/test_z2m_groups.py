import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from copy import deepcopy
from electrica.light_routes import discover_routes, current_route
from electrica.mqtt_lights import plan_batch
from electrica.runtime import Application, verified_snapshots
from electrica.catalog import candidate_from_mqtt
from test_mqtt_light_output import BASE,COORD,A,B,SN,SKEY,DEV,DEVICES,ENTITIES,light,switch,FakeMQTT,msg

GROUP="zg_livingroom_lights"
EID="light.zg_livingroom_lights"
GROUPS=[{"id":110,"friendly_name":GROUP,"members":[{"endpoint":11,"ieee_address":A},{"endpoint":11,"ieee_address":B}],"scenes":[]}]
INVENTORY=deepcopy(DEV)
for d in INVENTORY:
    if d.get("ieee_address") in (A,B):
        d["endpoints"]={"11":{"clusters":{"input":["genOnOff","genLevelCtrl","lightingColorCtrl"]}}}
    if d.get("ieee_address")==A:
        d["definition"]["exposes"][0]["features"]=[f for f in d["definition"]["exposes"][0]["features"] if f.get("name")!="color_xy"]
GROUP_ENTITY={"entity_id":EID,"platform":"mqtt","unique_id":f"110_light_{BASE}","disabled_by":None}
SNAP={"base_topic":BASE,"coordinator_ieee":COORD,"devices":json.dumps(INVENTORY).encode(),"groups":json.dumps(GROUPS).encode(),"states":{}}

def routes():
    return discover_routes([SNAP],DEVICES,[*ENTITIES,GROUP_ENTITY])
def network():
    return {**SNAP,"bridge_state":"online","info":json.dumps({"coordinator":{"ieee_address":COORD}}).encode(),
        "states":{"chandelier":{"state":"OFF"},"spots":{"state":"OFF"}}}

class GroupTests(unittest.TestCase):
    def test_exact_identity_and_common_capabilities(self):
        route=routes()[EID]
        self.assertEqual(route["group_id"],110)
        self.assertEqual(set(route["features"]),{"state","brightness","color_temp"})
        self.assertFalse(route["features"]["state"]["readable"])
        wrong={**GROUP_ENTITY,"unique_id":"110_light_other"}
        self.assertNotIn(EID,discover_routes([SNAP],DEVICES,[*ENTITIES,wrong]))
        renamed={**GROUP_ENTITY,"entity_id":"light.renamed_ha"}
        self.assertIn("light.renamed_ha",discover_routes([SNAP],DEVICES,[*ENTITIES,renamed]))
        changed=deepcopy(GROUPS);changed[0]["members"][0]["endpoint"]=12
        self.assertFalse(current_route(route,{**network(),"groups":json.dumps(changed).encode()}))
    def test_group_direct_toggle_and_unsupported_rgb(self):
        route=routes()
        net=network()
        fresh={(BASE,"chandelier","state"),(BASE,"spots","state")}
        availability={(BASE,GROUP):"online"}
        command={"service":"light.toggle","target":{"entity_id":[EID]},"data":{"brightness_pct":100,"color_temp_kelvin":2700}}
        plans,skips=plan_batch([command],route,{BASE:net},availability,fresh,{}, {},1)
        self.assertFalse(skips)
        self.assertEqual(len(plans),1)
        self.assertEqual(plans[0]["topic"],BASE+"/"+GROUP+"/set")
        self.assertEqual(plans[0]["payload"],{"state":"ON","brightness":254,"color_temp":370})
        net["states"][GROUP]={"state":"ON"}
        fresh.add((BASE,GROUP,"state"))
        plans,_=plan_batch([command],route,{BASE:net},availability,fresh,{}, {},2)
        self.assertEqual(plans[0]["payload"],{"state":"OFF"})
        command["data"]={"rgb_color":[255,0,0]}
        net["states"][GROUP]["state"]="OFF"
        plans,skips=plan_batch([command],route,{BASE:net},availability,fresh,{}, {},3)
        self.assertFalse(plans)
        self.assertIn("color",skips[0]["reason"])
        self.assertFalse(plan_batch([command],route,{BASE:net},{},fresh,{}, {},4)[0])
        self.assertFalse(plan_batch([command],route,{BASE:net},availability,set(),{}, {},4)[0])
    def test_runtime_group_report_confirms_one_group_command(self):
        saved=candidate_from_mqtt(switch(),coordinator_ieee=COORD,base_topic=BASE,reported_state={})
        saved.update({"entity_id":SKEY,"enabled":True,"bindings":{}})
        adopted={"rooms":[{"name":"Living","area_id":None,"switches":[saved]}],"light_routes":routes()}
        opts=Mock();opts.read.return_value={"switches":f"- {SKEY}: {{enabled: true, actions: {{single: [{EID}]}}}}"}
        ha=Mock()
        with TemporaryDirectory() as td,patch("electrica.entity_options._read_profiles",return_value=adopted):
            app=Application(FakeMQTT,options=opts,registry=Mock(),last_scan_path=Path(td)/"scan.json",version="0.2.3",ha_client=ha)
        app._on_connect(None,None,None,0)
        for suffix,data in [("info",{"coordinator":{"ieee_address":COORD}}),("devices",INVENTORY),("groups",GROUPS),("state",{"state":"online"})]:
            app._on_message(None,None,msg(BASE+"/bridge/"+suffix,data,True))
        self.assertEqual(verified_snapshots(app._networks)[0]["groups"],json.dumps(GROUPS).encode())
        app._on_message(None,None,msg(BASE+"/"+GROUP+"/availability",b"online",True))
        for name in ("chandelier","spots"):
            app._on_message(None,None,msg(BASE+"/"+name,{"state":"OFF"}))
        app._on_message(None,None,msg(BASE+"/"+SN,{"action":"single"}))
        self.assertEqual(app._jobs.qsize(),1)
        app._publish_action=lambda **_:app._stop.set()
        app._run_actions()
        outgoing=[(topic,json.loads(data),retain) for topic,data,retain in app.client.published if topic.endswith("/set")]
        self.assertEqual(outgoing,[(BASE+"/"+GROUP+"/set",{"state":"ON"},False)])
        self.assertEqual(app.event_log.snapshot()["rows"][-1]["targets"][EID]["status"],"sent")
        app._on_message(None,None,msg(BASE+"/"+GROUP,{"state":"ON"},True))
        self.assertEqual(app.event_log.snapshot()["rows"][-1]["targets"][EID]["status"],"sent")
        app._on_message(None,None,msg(BASE+"/"+GROUP,{"state":"ON"}))
        self.assertEqual(app.event_log.snapshot()["rows"][-1]["targets"][EID]["status"],"confirmed")
        ha.execute.assert_not_called()
