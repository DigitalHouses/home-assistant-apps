"""Sensor-driven multicast uses individual member ownership, not group ACK."""
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from test_sensor_engine import SOURCE,motion,state
from test_z2m_groups import EID,GROUP,GROUPS,INVENTORY,BASE,COORD,routes,msg
from test_mqtt_light_output import L1,L2
import test_ha_native_output as native
from electrica.sensor_engine import SensorEngine

class SensorGroupTests(unittest.TestCase):
    def setup_group(self,values=("off","off"),delay=0):
        app,ha,_=native.NativeLightIntegration().build([L1])
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app.sensor_engine=SensorEngine(app,Path(tmp.name)/"timers.json")
        e=app.sensor_engine
        app.config["light_routes"]=routes()
        app.config["sensor_bindings"]={SOURCE:{"entity_id":SOURCE,"enabled":True,"assignments":[
            {"entity_id":EID,"operation":"on","data":{},"off_delay_seconds":delay}]}}
        app.sensor_catalog={SOURCE:{"lux_sources":[]}}
        app.target_catalog={eid:{"brightness":True,"state":"off","integration":"mqtt","group":eid==EID}
                            for eid in (L1,L2,EID)}
        for suffix,data in [("info",{"coordinator":{"ieee_address":COORD}}),("devices",INVENTORY),
                            ("groups",GROUPS),("state",{"state":"online"})]:
            app._on_message(None,None,msg(BASE+"/bridge/"+suffix,data,True))
        for name in ("chandelier","spots",GROUP):
            app._on_message(None,None,msg(BASE+"/"+name+"/availability",b"online",True))
        for name,value in zip(("chandelier","spots"),values):
            app._on_message(None,None,msg(BASE+"/"+name,{"state":value.upper()}))
        e.baseline([motion("off"),state(L1,values[0]),state(L2,values[1]),state(EID,"off")])
        return app,ha,e

    def run_job(self,app):
        results=[]
        app._stop.clear()
        app._publish_action=lambda **kw:(results.append(kw),app._stop.set())
        app._run_actions()
        app._stop.clear()
        return results[0]["state"]

    def payloads(self,app):
        return [(t,json.loads(b)) for t,b,_ in app.client.published if t.endswith("/set")]

    def confirm(self,app,e):
        for eid,name in [(L1,"chandelier"),(L2,"spots")]:
            app._on_message(None,None,msg(BASE+"/"+name,{"state":"ON"}))
            e.changed(eid,state(eid,"on","2026-11-26T08:01:01+00:00",brightness=76))
        app._on_message(None,None,msg(BASE+"/"+GROUP,{"state":"ON"}))
        app.registry.fetch_states.return_value=list(e.states.values())

    def activate(self,app,e):
        e.changed(SOURCE,motion("on"))
        self.assertEqual(app._jobs.qsize(),1)
        self.assertEqual(self.run_job(app),"sent")

    def test_single_multicast_and_individual_confirmation(self):
        app,ha,e=self.setup_group()
        self.activate(app,e)
        self.assertEqual(self.payloads(app),[(BASE+"/"+GROUP+"/set",{"state":"ON"})])
        e.changed(EID,state(EID,"on"))
        self.assertNotIn(EID,e.owners)
        self.confirm(app,e)
        self.assertEqual(set(e.owners[EID]["signature"]["members"]),{L1,L2})
        e.changed(SOURCE,motion("off"))
        e.tick()
        self.assertEqual(self.run_job(app),"sent")
        self.assertEqual(self.payloads(app)[-1],(BASE+"/"+GROUP+"/set",{"state":"OFF"}))
        ha.execute.assert_not_called()

    def test_mixed_group_and_missing_member_not_activated(self):
        app,ha,e=self.setup_group(("on","off"))
        e.changed(SOURCE,motion("on"))
        self.assertTrue(app._jobs.empty())
        app,ha,e=self.setup_group()
        app.config["light_routes"].pop(L2)
        e.changed(SOURCE,motion("on"))
        self.assertTrue(app._jobs.empty())

    def test_manual_member_change_revokes_whole_group(self):
        app,ha,e=self.setup_group()
        self.activate(app,e)
        self.confirm(app,e)
        e.manual_control([L1])
        self.assertNotIn(EID,e.owners)
        e.changed(SOURCE,motion("off"));e.tick()
        self.assertTrue(app._jobs.empty())
        app,ha,e=self.setup_group()
        self.activate(app,e);self.confirm(app,e)
        e.changed(L1,state(L1,"on","2026-11-26T08:01:01+00:00",brightness=180))
        self.assertNotIn(EID,e.owners)

    def test_membership_change_and_unseen_external_change_block_off(self):
        app,ha,e=self.setup_group()
        self.activate(app,e);self.confirm(app,e)
        e.changed(SOURCE,motion("off"));e.tick()
        changed=deepcopy(GROUPS);changed[0]["members"].pop()
        app._on_message(None,None,msg(BASE+"/bridge/groups",changed,True))
        self.assertEqual(self.run_job(app),"skipped")
        self.assertEqual(len(self.payloads(app)),1)
        app,ha,e=self.setup_group()
        self.activate(app,e);self.confirm(app,e)
        e.changed(SOURCE,motion("off"));e.tick()
        app.registry.fetch_states.return_value=[s if s["entity_id"]!=L2 else
            state(L2,"on","2026-11-26T08:01:01+00:00",brightness=190) for s in e.states.values()]
        self.assertEqual(self.run_job(app),"skipped")
        self.assertEqual(len(self.payloads(app)),1)

    def test_overlap_and_offline_member_block_activation(self):
        app,ha,e=self.setup_group()
        app.config["sensor_bindings"][SOURCE]["assignments"].append({"entity_id":L1,"operation":"on","data":{}})
        e.changed(SOURCE,motion("on"))
        self.assertTrue(app._jobs.empty())
        app,ha,e=self.setup_group()
        app._on_message(None,None,msg(BASE+"/spots/availability",b"offline",True))
        e.changed(SOURCE,motion("on"))
        self.assertTrue(app._jobs.empty())

    def test_restart_restores_only_matching_members(self):
        app,ha,e=self.setup_group(delay=60)
        self.activate(app,e);self.confirm(app,e)
        e.changed(SOURCE,motion("off"))
        deadline=e.owners[EID]["deadline"]
        restored=SensorEngine(app,e.path)
        restored.baseline(list(e.states.values()))
        self.assertEqual(restored.owners[EID]["deadline"],deadline)
        restored.baseline([s for s in e.states.values() if s["entity_id"]!=L2])
        self.assertNotIn(EID,restored.owners)

    def test_profile_change_per_member_preserves_group_timer(self):
        app,ha,e=self.setup_group(delay=60)
        app.config["sensor_bindings"][SOURCE]["assignments"][0]["data"]={"profile":"current"}
        from test_profiles import SNAP
        app._home_profile=deepcopy(SNAP)
        self.activate(app,e);self.confirm(app,e)
        e.changed(SOURCE,motion("off"))
        deadline=e.owners[EID]["deadline"]
        e.expect_profile(EID,{"brightness_pct":100})
        e.changed(L1,state(L1,"on","2026-11-26T08:01:01+00:00",brightness=255))
        self.assertIn(EID,e.owners)
        e.changed(L2,state(L2,"on","2026-11-26T08:01:01+00:00",brightness=255))
        self.assertEqual(e.owners[EID]["deadline"],deadline)
        self.assertNotIn(EID,e.profile_changes)

    def test_changed_route_after_queue_blocks_on(self):
        app,ha,e=self.setup_group()
        e.changed(SOURCE,motion("on"))
        changed=deepcopy(GROUPS);changed[0]["members"].pop()
        app._on_message(None,None,msg(BASE+"/bridge/groups",changed,True))
        self.assertEqual(self.run_job(app),"skipped")
        self.assertFalse(self.payloads(app))
