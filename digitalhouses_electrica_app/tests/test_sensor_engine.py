"""Motion and timer integration tests exercise the real serialized action worker."""
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import json

from electrica.sensor_engine import SensorEngine
from electrica import profiles
from test_ha_native_output import TV
import test_ha_native_output as native
from test_lab_rest_fallback import PHYSICAL
from test_profiles import SNAP

SOURCE="binary_sensor.room"
LUX="sensor.room_lux"

def state(eid,value,stamp="2026-11-26T08:00:00+00:00",**attrs):
    return {"entity_id":eid,"state":value,"last_changed":stamp,
            "last_updated":datetime.now(timezone.utc).isoformat(),"attributes":attrs}

def motion(value,stamp="2026-11-26T08:00:00+00:00",eid=SOURCE):
    return state(eid,value,stamp,device_class="occupancy")

class SensorEngineTests(unittest.TestCase):
    def app(self,*,eid=TV,delay=60,lux=True,profile=False,physical=False,target_state="off"):
        app,ha,_=native.NativeLightIntegration().build([TV],tv=target_state,route=physical,physical=target_state.upper())
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app.sensor_engine=SensorEngine(app,Path(tmp.name)/"timers.json")
        row={"entity_id":SOURCE,"enabled":True,"assignments":[
            {"entity_id":eid,"operation":"on","data":{"profile":"current"} if profile else {},
             "off_delay_seconds":delay}]}
        if lux:row.update(lux_entity_id=LUX,lux_threshold=70)
        app.config["sensor_bindings"]={SOURCE:row}
        app.sensor_catalog={SOURCE:{"lux_sources":[{"entity_id":LUX}] if lux else []}}
        app.target_catalog={eid:{"brightness":True,"state":target_state,"integration":"mqtt" if physical else "template"}}
        app._home_profile=deepcopy(SNAP)
        engine=app.sensor_engine
        engine.baseline([motion("off"),state(eid,target_state),
                         state(LUX,"35",device_class="illuminance",unit_of_measurement="lx")])
        return app,ha,engine

    def run_job(self,app):
        result=[]
        app._stop.clear()
        app._publish_action=lambda **kw:(result.append(kw),app._stop.set())
        app._run_actions()
        app._stop.clear()
        self.assertEqual(app._jobs.unfinished_tasks,0)
        return result

    def activate(self,app,ha,e):
        e.changed(SOURCE,motion("on","2026-11-26T08:01:00+00:00"))
        self.assertEqual(app._jobs.qsize(),1)
        self.assertEqual(self.run_job(app)[0]["state"],"sent")
        e.changed(TV,state(TV,"on","2026-11-26T08:01:01+00:00",brightness=76))
        ha.read_light_state.return_value="on"
        ha.read_domain_state.return_value=deepcopy(e.states[TV])
        self.assertIn(TV,e.owners)

    def test_native_motion_profile_and_off_timer(self):
        app,ha,e=self.app(profile=True,delay=0)
        self.activate(app,ha,e)
        ha.execute.assert_called_once_with({"service":"light.turn_on","target":{"entity_id":[TV]},"data":{"brightness_pct":30}})
        e.changed(SOURCE,motion("off","2026-11-26T08:02:00+00:00"))
        e.tick()
        self.assertEqual(app._jobs.qsize(),1)
        self.assertEqual(self.run_job(app)[0]["state"],"sent")
        self.assertEqual(ha.execute.call_args.args[0]["service"],"light.turn_off")
        self.assertNotIn(TV,e.owners)

    def test_verified_zigbee_motion_uses_mqtt_not_ha(self):
        app,ha,e=self.app(eid=PHYSICAL,physical=True,delay=0)
        e.changed(SOURCE,motion("on"))
        self.assertEqual(self.run_job(app)[0]["state"],"sent")
        ha.execute.assert_not_called()
        self.assertIn({"state":"ON"},[json.loads(b) for t,b,_ in app.client.published if t.endswith("/set")])

    def test_no_startup_replay_or_unknown_to_on(self):
        app,ha,e=self.app()
        e.baseline([motion("on"),state(TV,"off")])
        self.assertTrue(app._jobs.empty())
        e.changed(SOURCE,motion("unavailable"))
        e.changed(SOURCE,motion("on"))
        self.assertTrue(app._jobs.empty())

    def test_lux_unknown_bright_and_zero_block_on(self):
        for value,threshold in (("unavailable",70),("70",70),("0",0)):
            app,ha,e=self.app()
            app.config["sensor_bindings"][SOURCE]["lux_threshold"]=threshold
            e.changed(LUX,state(LUX,value,device_class="illuminance",unit_of_measurement="lx"))
            e.changed(SOURCE,motion("on"))
            self.assertTrue(app._jobs.empty())

    def test_motion_repeat_cancels_queued_off(self):
        app,ha,e=self.app(delay=0)
        self.activate(app,ha,e)
        e.changed(SOURCE,motion("off"))
        e.tick()
        self.assertEqual(app._jobs.qsize(),1)
        e.changed(SOURCE,motion("on"))
        self.assertIsNone(e.owners[TV]["deadline"])
        self.assertEqual(self.run_job(app)[0]["state"],"skipped")
        self.assertEqual(ha.execute.call_count,1)
        self.assertIn(TV,e.owners)

    def test_manual_key_cancels_ownership_and_external_change_cancels(self):
        app,ha,e=self.app(delay=0)
        self.activate(app,ha,e)
        e.changed(SOURCE,motion("off"))
        e.tick()
        e.manual_control([TV])
        self.assertNotIn(TV,e.owners)
        self.assertEqual(self.run_job(app)[0]["state"],"skipped")
        self.assertEqual(ha.execute.call_count,1)
        app,ha,e=self.app()
        self.activate(app,ha,e)
        e.changed(TV,state(TV,"on","2026-11-26T08:01:01+00:00",brightness=150))
        self.assertNotIn(TV,e.owners)

    def test_other_sensor_presence_blocks_off(self):
        app,ha,e=self.app(delay=0)
        self.activate(app,ha,e)
        second="binary_sensor.second"
        app.config["sensor_bindings"][second]={**deepcopy(app.config["sensor_bindings"][SOURCE]),"entity_id":second}
        app.sensor_catalog[second]=deepcopy(app.sensor_catalog[SOURCE])
        e.changed(second,motion("on",eid=second))
        e.changed(SOURCE,motion("off"))
        e.tick()
        self.assertTrue(app._jobs.empty())
        e.changed(second,motion("off",eid=second))
        e.tick()
        self.assertEqual(app._jobs.qsize(),1)

    def test_deadline_restored_only_with_matching_baseline(self):
        app,ha,e=self.app(delay=30)
        self.activate(app,ha,e)
        e.changed(SOURCE,motion("off","2026-11-26T08:02:00+00:00"))
        deadline=e.owners[TV]["deadline"]
        states=list(e.states.values())
        restored=SensorEngine(app,e.path)
        restored.baseline(states)
        self.assertEqual(restored.owners[TV]["deadline"],deadline)
        # Changed light after restart invalidates old ownership.
        restored.baseline([s if s["entity_id"]!=TV else state(TV,"on","2026-11-26T08:03:00+00:00") for s in states])
        self.assertNotIn(TV,restored.owners)

    def test_already_on_and_group_are_not_taken_over(self):
        app,ha,e=self.app(target_state="on")
        e.changed(SOURCE,motion("on"))
        self.assertTrue(app._jobs.empty())
        app,ha,e=self.app()
        app.target_catalog[TV]["group"]=True
        e.changed(SOURCE,motion("on"))
        self.assertTrue(app._jobs.empty())

    def test_unknown_presence_never_counts_as_absence(self):
        app,ha,e=self.app(delay=0)
        self.activate(app,ha,e)
        e.changed(SOURCE,motion("unavailable"))
        e.tick()
        self.assertTrue(app._jobs.empty())
        self.assertIsNone(e.owners[TV]["deadline"])

    def test_dynamic_sensor_included_in_adaptation(self):
        app,ha,e=self.app(profile=True)
        # Remove the unrelated legacy fixed manual assignment for this target.
        app.config["rooms"][0]["switches"][0]["bindings"]={}
        self.assertEqual(profiles.adaptation_targets(app.config),([TV],[]))


    def test_confirmed_profile_change_retains_timer_but_manual_change_does_not(self):
        app,ha,e=self.app(profile=True,delay=60)
        self.activate(app,ha,e)
        self.assertTrue(e.dynamic_owner(TV))
        e.expect_profile(TV,{"brightness_pct":100})
        e.changed(TV,state(TV,"on","2026-11-26T08:01:01+00:00",brightness=255))
        self.assertIn(TV,e.owners)
        e.changed(TV,state(TV,"on","2026-11-26T08:01:01+00:00",brightness=160))
        self.assertNotIn(TV,e.owners)


    def test_external_change_not_yet_seen_by_subscription_blocks_native_off(self):
        app,ha,e=self.app(delay=0)
        self.activate(app,ha,e)
        e.changed(SOURCE,motion("off"))
        e.tick()
        ha.read_domain_state.return_value=state(TV,"on","2026-11-26T08:01:01+00:00",brightness=200)
        self.assertEqual(self.run_job(app)[0]["state"],"skipped")
        self.assertEqual(ha.execute.call_count,1)

    def test_switch_uses_existing_verified_engine(self):
        eid="switch.fan"
        app,ha,e=self.app(eid=eid,delay=0)
        app.registry.fetch.return_value=([],[],[{"entity_id":eid,"device_id":"fan","platform":"mqtt","disabled_by":None}])
        ha.read_switch_state.return_value="off"
        e.changed(SOURCE,motion("on"))
        self.assertEqual(self.run_job(app)[0]["state"],"sent")
        ha.execute_switch.assert_called_once_with(eid,"on")
        e.changed(eid,state(eid,"on","2026-11-26T08:01:00+00:00"))
        ha.read_switch_state.return_value="on"
        ha.read_domain_state.return_value=deepcopy(e.states[eid])
        e.changed(SOURCE,motion("off"))
        e.tick()
        self.assertEqual(self.run_job(app)[0]["state"],"sent")
        ha.execute_switch.assert_called_with(eid,"off")

    def test_no_delay_only_on(self):
        app,ha,e=self.app(delay=None)
        e.changed(SOURCE,motion("on"))
        self.run_job(app)
        e.changed(TV,state(TV,"on"))
        e.changed(SOURCE,motion("off"))
        e.tick()
        self.assertTrue(app._jobs.empty())
        self.assertNotIn(TV,e.owners)
