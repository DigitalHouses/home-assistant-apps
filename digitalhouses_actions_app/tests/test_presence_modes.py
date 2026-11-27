"""Mode-filtered presence rules, owned transitions and backwards compatibility."""
from copy import deepcopy
import unittest
from pathlib import Path
from datetime import datetime,timezone

from actions import sensor_rules, profiles
from actions.binding_store import validate_document
from actions.catalog import CatalogError
from actions.entity_options import parse_rows,render_rows
from actions.ingress import validate_sensor_assignment
import test_sensor_engine as sensor_tests
from test_sensor_engine import SOURCE, motion,state,TV
from test_profiles import SNAP

CEILING="light.ceiling"
FLOOR="light.floor"

def assignment(eid,when=None,data=None,night=None):
    a={"entity_id":eid,"operation":"on","data":data or {},"off_delay_seconds":0}
    if when is not None:a["when"]=when
    if night is not None:a["night_data"]=night
    return a

class PresenceModeTests(unittest.TestCase):
    def test_bathroom_matrix_and_roundtrip(self):
        row={"entity_id":SOURCE,"enabled":True,"assignments":[
            assignment(CEILING,"day"),
            assignment(FLOOR,data={"brightness_pct":100},night={"brightness_pct":20})]}
        doc={"schema":1,"rows":[row]}
        self.assertEqual(validate_document(doc),doc)
        self.assertEqual(parse_rows({"switches":render_rows([row])}),[row])
        ids={CEILING,FLOOR}
        self.assertEqual(sensor_rules.commands(row,ids,"on","day"),[
            {"service":"light.turn_on","target":{"entity_id":[CEILING]}},
            {"service":"light.turn_on","target":{"entity_id":[FLOOR]},"data":{"brightness_pct":100}}])
        self.assertEqual(sensor_rules.commands(row,ids,"on","night"),[
            {"service":"light.turn_on","target":{"entity_id":[FLOOR]},"data":{"brightness_pct":20}}])
        self.assertEqual(sensor_rules.commands(row,ids,"on",None),[])
        self.assertEqual(len(sensor_rules.commands(row,ids,"off","night")),2)
        row["assignments"].append(assignment("switch.fan"))
        self.assertEqual(sensor_rules.commands(row,{"switch.fan"},"on",None),[
            {"service":"switch.turn_on","target":{"entity_id":["switch.fan"]}}])

    def test_invalid_modes_and_custom_parameters(self):
        for a in (assignment(CEILING,"evening"),assignment(FLOOR,"night",night={"brightness_pct":20}),
                  assignment("switch.fan",night={}),assignment(FLOOR,night={"brightness_pct":101}),
                  assignment(FLOOR,night={"brightness_step_pct":20})):
            with self.assertRaises(CatalogError):
                sensor_rules.validate_row({"entity_id":SOURCE,"enabled":True,"assignments":[a]})
        a=assignment(FLOOR,night={"brightness_pct":20})
        row={"entity_id":SOURCE,"enabled":True,"assignments":[a]}
        with self.assertRaises(CatalogError):
            validate_sensor_assignment(row,{SOURCE:{"lux_sources":[]}},{FLOOR:{"brightness":False}})

    def build(self,a,mode="day",auto=True):
        helper=sensor_tests.SensorEngineTests()
        self.addCleanup(helper.doCleanups)
        app,ha,e=helper.app(delay=0,lux=False)
        app.config["sensor_bindings"][SOURCE]["assignments"]=[a]
        app.config["rooms"][0]["switches"][0]["bindings"]={}
        app.globals["auto_day_night"]=auto
        app._home_profile={**deepcopy(SNAP),"mode":mode} if mode else None
        app._target_registries=([],[],[{"entity_id":TV,"platform":"template"}])
        return helper,app,ha,e

    def transition(self,app,mode):
        app._accept_home_profile({**deepcopy(SNAP),"mode":mode})
        if not app._jobs.empty():
            job=app._jobs.get_nowait()
            self.assertEqual(job[3],"AUTO_PROFILE")
            app._adapt_home_profile(job[6],job[5])
            app._jobs.task_done()

    def activate(self,helper,app,ha,e):
        e.changed(SOURCE,motion("on","2026-11-26T08:01:00+00:00"))
        self.assertEqual(app._jobs.qsize(),1)
        self.assertEqual(helper.run_job(app)[0]["state"],"sent")
        app._ha_state_changed(TV,state(TV,"on",datetime.now(timezone.utc).isoformat(),brightness=255,
                          supported_color_modes=["brightness"],color_mode="brightness"))
        ha.read_light_state.return_value="on"
        ha.read_domain_state.return_value=deepcopy(e.states[TV])
        self.assertIn(TV,e.owners)

    def test_filtered_presence_and_stale_queue(self):
        for when,mode,expected in (("day","day",1),("day","night",0),("night","night",1),
                                   ("night","day",0),("day",None,0),(None,None,1)):
            with self.subTest(when=when,mode=mode):
                h,app,ha,e=self.build(assignment(TV,when),mode)
                e.changed(SOURCE,motion("on"))
                self.assertEqual(app._jobs.qsize(),expected)
        h,app,ha,e=self.build(assignment(TV,"day"))
        e.changed(SOURCE,motion("on"))
        app._home_profile={**SNAP,"mode":"night"}
        self.assertEqual(h.run_job(app)[0]["state"],"skipped")
        ha.execute.assert_not_called()

    def test_owned_ceiling_turns_off_on_night_and_no_wake(self):
        h,app,ha,e=self.build(assignment(TV,"day"))
        self.activate(h,app,ha,e)
        self.transition(app,"night")
        self.assertEqual(app._jobs.qsize(),1)
        self.assertEqual(h.run_job(app)[0]["state"],"sent")
        self.assertEqual(ha.execute.call_args.args[0]["service"],"light.turn_off")
        self.assertNotIn(TV,e.owners)
        e.changed(TV,state(TV,"off"))
        ha.read_light_state.return_value="off"
        self.transition(app,"day")
        self.assertTrue(app._jobs.empty())
        self.assertEqual(ha.execute.call_count,2)

    def test_manual_shared_and_disabled_auto_not_switched_off(self):
        for kind in ("manual","other_sensor","disabled","stale"):
            h,app,ha,e=self.build(assignment(TV,"day"),auto=kind!="disabled")
            self.activate(h,app,ha,e)
            if kind=="manual":e.manual_control([TV])
            if kind=="other_sensor":
                other="binary_sensor.other"
                app.config["sensor_bindings"][other]={**deepcopy(app.config["sensor_bindings"][SOURCE]),"entity_id":other}
                app.sensor_catalog[other]={"lux_sources":[]}
                e.changed(other,motion("on",eid=other))
            self.transition(app,"night")
            if kind=="stale":
                self.assertEqual(app._jobs.qsize(),1)
                app._home_profile={**deepcopy(SNAP),"mode":"day"}
                self.assertEqual(h.run_job(app)[0]["state"],"skipped")
            else:self.assertTrue(app._jobs.empty())
            self.assertEqual(ha.execute.call_count,1)

    def test_night_custom_brightness_and_timer_ownership(self):
        h,app,ha,e=self.build(assignment(TV,data={"brightness_pct":100},night={"brightness_pct":20}))
        self.activate(h,app,ha,e)
        self.assertEqual(ha.execute.call_args.args[0]["data"],{"brightness_pct":100})
        self.transition(app,"night")
        self.assertEqual(ha.execute.call_args.args[0]["data"],{"brightness_pct":20})
        app._ha_state_changed(TV,state(TV,"on",e.states[TV]["last_changed"],brightness=51,
                          supported_color_modes=["brightness"],color_mode="brightness"))
        self.assertIn(TV,e.owners)
        ha.read_domain_state.return_value=deepcopy(e.states[TV])
        self.transition(app,"day")
        self.assertEqual(ha.execute.call_args.args[0]["data"],{"brightness_pct":100})
        app._ha_state_changed(TV,state(TV,"on",e.states[TV]["last_changed"],brightness=255,
                          supported_color_modes=["brightness"],color_mode="brightness"))
        ha.read_domain_state.return_value=deepcopy(e.states[TV])
        e.changed(SOURCE,motion("off"))
        e.tick()
        self.assertEqual(h.run_job(app)[0]["state"],"sent")
        self.assertEqual(ha.execute.call_args.args[0]["service"],"light.turn_off")

    def test_night_presence_uses_custom_not_global(self):
        h,app,ha,e=self.build(assignment(TV,data={"brightness_pct":100},night={"brightness_pct":20}),"night")
        e.changed(SOURCE,motion("on"))
        self.assertEqual(h.run_job(app)[0]["state"],"sent")
        self.assertEqual(ha.execute.call_args.args[0]["data"],{"brightness_pct":20})
        log=app.event_log.snapshot()["rows"][-1]["targets"][TV]
        self.assertEqual(log["parameters"],{"brightness_pct":20})
        self.assertEqual(log["expected_parameters"],{"brightness_pct":20})

    def test_no_implicit_ownership_for_already_on_light(self):
        h,app,ha,e=self.build(assignment(TV,data={"brightness_pct":100},night={"brightness_pct":20}))
        e.changed(TV,state(TV,"on",brightness=255))
        e.changed(SOURCE,motion("on"))
        self.transition(app,"night")
        self.assertTrue(app._jobs.empty())
        ha.execute.assert_not_called()

    def test_z2m_mode_off_and_custom_profile_without_ha_light_calls(self):
        import json
        from test_ha_native_output import BASE,PHYSICAL,PHYSICAL_DEVICE,COORD,DEVICE,packet
        from test_mqtt_light_output import light
        from actions.light_routes import _light_features
        for custom in (False,True):
            h=sensor_tests.SensorEngineTests()
            self.addCleanup(h.doCleanups)
            app,ha,e=h.app(eid=PHYSICAL,physical=True,delay=0,lux=False)
            a=assignment(PHYSICAL,data={"brightness_pct":100},night={"brightness_pct":20}) if custom else assignment(PHYSICAL,"day")
            app.config["sensor_bindings"][SOURCE]["assignments"]=[a]
            app.config["rooms"][0]["switches"][0]["bindings"]={}
            app.globals["auto_day_night"]=True
            app._home_profile={**deepcopy(SNAP),"mode":"day"}
            dev=light(PHYSICAL_DEVICE["ieee_address"],PHYSICAL_DEVICE["friendly_name"])
            app.config["light_routes"][PHYSICAL]["features"]=_light_features(dev)
            app._on_message(None,None,packet(BASE+"/bridge/devices",[{"type":"Coordinator","ieee_address":COORD},DEVICE,dev],True))
            app.target_catalog[PHYSICAL]={"brightness":True,"state":"off","integration":"mqtt"}
            e.changed(SOURCE,motion("on"))
            self.assertEqual(h.run_job(app)[0]["state"],"sent")
            app._on_message(None,None,packet(BASE+"/led_strip",{"state":"ON","brightness":254}))
            app._ha_state_changed(PHYSICAL,state(PHYSICAL,"on",datetime.now(timezone.utc).isoformat(),brightness=255))
            self.assertIn(PHYSICAL,e.owners)
            self.transition(app,"night")
            if not custom:
                self.assertEqual(app._jobs.qsize(),1)
                self.assertEqual(h.run_job(app)[0]["state"],"sent")
            payloads=[json.loads(body) for topic,body,_ in app.client.published if topic.endswith("/set")]
            self.assertEqual(payloads[-1],{"brightness":51} if custom else {"state":"OFF"})
            ha.execute.assert_not_called()

    def test_ingress_controls(self):
        js=(Path(__file__).resolve().parents[1]/"rootfs/app/actions/web/app.js").read_text()
        self.assertIn('for(const mode of ["day","night"])',js)
        self.assertIn('enabled.checked=block.enabled',js)
        self.assertIn('block.off_delay_seconds',js)
        self.assertIn('Глобальные параметры "+title',js)
        self.assertNotIn("Отдельные параметры ночью",js)
