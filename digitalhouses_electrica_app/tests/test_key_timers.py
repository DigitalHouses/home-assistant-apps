import json
import time
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock,patch

from electrica.runtime import Application
from electrica.sensor_engine import SensorEngine
from electrica.light_rules import parse_rule
from electrica.ingress_catalog import normalize
from electrica.binding_store import validate_document
from electrica.catalog import CatalogError
from electrica.entity_options import render_rows
import test_sensor_engine as sensor_tests
from test_sensor_engine import TV, state
from test_lab_rest_fallback import BASE as BAT_BASE,NAME as BAT_NAME,packet
from test_mode_keeper import BASE,COORD,ENTITY,NAME,profiles,wired
from test_mqtt_light_output import FakeMQTT,msg


class KeyTimerTests(unittest.TestCase):
    def native(self,delay=60):
        helper=sensor_tests.SensorEngineTests()
        self.addCleanup(helper.doCleanups)
        app,ha,e=helper.app()
        app.config.pop("sensor_bindings")
        sw=app.config["rooms"][0]["switches"][0]
        assignment={"entity_id":TV,"operation":"toggle","data":{},"off_delay_seconds":delay}
        sw["bindings"]["double"]=parse_rule({"assignments":[assignment]})
        return helper,app,ha,e,sw,assignment

    def test_roundtrip_and_invalid_timer_fields(self):
        _,_,_,_,sw,a=self.native()
        self.assertEqual(normalize({"assignments":[a]}),[a])
        row={"entity_id":sw["entity_id"],"enabled":True,"actions":{"double":{"assignments":[a]}}}
        self.assertEqual(validate_document({"schema":1,"rows":[row]})["rows"],[row])
        for bad in [{**a,"off_delay_seconds":0},{**a,"off_delay_seconds":True},
                    {**a,"off_delay_seconds":86401},{**a,"operation":"off"},
                    {**a,"entity_id":"cover.room","operation":"open"}]:
            with self.assertRaises(CatalogError):parse_rule({"assignments":[bad]})
        physical={"entity_id":ENTITY,"enabled":True,"actions":{},"keep_mode":{"right":"control_relay"},"relay_timers":{"right":1800}}
        self.assertEqual(validate_document({"schema":1,"rows":[physical]})["rows"],[physical])
        for bad in [{**physical,"keep_mode":{"right":"decoupled/ON"}},
                    {**physical,"relay_timers":{"left":1800}},
                    {**physical,"relay_timers":{"right":0}}]:
            with self.assertRaises(CatalogError):validate_document({"schema":1,"rows":[bad]})

    def press(self,helper,app):
        app._last_action_at.clear()
        app._on_message(None,None,packet(BAT_BASE+"/"+BAT_NAME,{"action":"double"}))
        self.assertEqual(app._jobs.qsize(),1)
        return helper.run_job(app)[0]["state"]

    def confirm(self,e,ha):
        e.changed(TV,state(TV,"on","2026-11-26T08:01:01+00:00"))
        ha.read_light_state.return_value="on"
        ha.read_domain_state.return_value=deepcopy(e.states[TV])

    def test_logical_timer_starts_at_confirmed_on_and_restores(self):
        h,app,ha,e,_,_=self.native()
        self.assertEqual(self.press(h,app),"sent")
        self.assertNotIn(TV,e.owners)
        self.confirm(e,ha)
        self.assertTrue(e.owners[TV]["source"].startswith("key:"))
        deadline=e.owners[TV]["deadline"]
        self.assertGreater(deadline,time.time()+50)
        restored=SensorEngine(app,e.path)
        restored.baseline(list(e.states.values()))
        self.assertEqual(restored.owners[TV]["deadline"],deadline)
        e.owners[TV]["deadline"]=time.time()-1
        e.tick()
        self.assertEqual(h.run_job(app)[0]["state"],"sent")
        self.assertEqual(ha.execute.call_args.args[0]["service"],"light.turn_off")
        self.assertNotIn(TV,e.owners)

    def test_manual_override_and_binding_change_cancel(self):
        h,app,ha,e,sw,_=self.native()
        self.press(h,app);self.confirm(e,ha)
        e.owners[TV]["deadline"]=time.time()-1;e.tick()
        e.manual_control([TV])
        self.assertEqual(h.run_job(app)[0]["state"],"skipped")
        self.assertEqual(ha.execute.call_count,1)
        h,app,ha,e,sw,_=self.native()
        self.press(h,app);self.confirm(e,ha)
        sw["bindings"]["double"]["target_timers"][TV]=120
        e.tick()
        self.assertNotIn(TV,e.owners)

    def test_toggle_off_and_unconfirmed_on_have_no_timer(self):
        h,app,ha,e,_,_=self.native()
        self.press(h,app);self.confirm(e,ha)
        app._ha_shadows.clear()
        self.assertEqual(self.press(h,app),"sent")
        self.assertEqual(ha.execute.call_args.args[0]["service"],"light.turn_off")
        self.assertNotIn(TV,e.owners)
        self.assertNotIn(TV,e.pending)


class PhysicalTimerTests(unittest.TestCase):
    def setup_relay(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        opts=Mock()
        opts.read.return_value={"switches":render_rows([{"entity_id":ENTITY,"enabled":True,
             "actions":{},"keep_mode":{"left":"decoupled/ON","right":"control_relay"},
             "relay_timers":{"right":60}}])}
        with patch("electrica.entity_options._read_profiles",return_value=profiles()):
            app=Application(FakeMQTT,options=opts,registry=Mock(),last_scan_path=Path(tmp.name)/"scan.json",
                version="0.2.3",ha_client=Mock())
        app._on_connect(None,None,None,0)
        for suffix,data in [("info",{"coordinator":{"ieee_address":COORD}}),
                            ("devices",[{"type":"Coordinator","ieee_address":COORD},wired()]),
                            ("state",{"state":"online"})]:
            app._on_message(None,None,msg(BASE+"/bridge/"+suffix,data,True))
        app._on_message(None,None,msg(BASE+"/"+NAME+"/availability",b"online",True))
        return app

    def report(self,app,relay="ON",mode="control_relay",retained=False):
        app._on_message(None,None,msg(BASE+"/"+NAME,
            {"operation_mode_right":mode,"state_right":relay,
             "operation_mode_left":"decoupled","state_left":"ON"},retained))

    def expire(self,app):
        rec=app.relay_timers.records[(ENTITY,"right")]
        rec["deadline"]=time.monotonic()-1
        app.relay_timers.tick()
        self.assertEqual(app._jobs.qsize(),1)

    def run_job(self,app):
        results=[]
        app._stop.clear()
        app._publish_action=lambda **kw:(results.append(kw),app._stop.set())
        app._run_actions()
        app._stop.clear()
        return results[0]["state"]

    def payloads(self,app):
        return [json.loads(b) for t,b,_ in app.client.published if t.endswith("/set")]

    def test_one_exact_channel_off_after_fresh_on(self):
        app=self.setup_relay()
        self.report(app,retained=True)
        app.relay_timers.tick()
        self.assertFalse(app.relay_timers.records)
        self.report(app)
        rec=app.relay_timers.records[(ENTITY,"right")]
        deadline=rec["deadline"]
        self.report(app)
        self.assertEqual(rec["deadline"],deadline)
        self.expire(app)
        self.assertEqual(self.run_job(app),"sent")
        self.assertEqual(self.payloads(app),[{"state_right":"OFF"}])
        app.relay_timers.tick()
        self.assertTrue(app._jobs.empty())
        self.report(app,relay="OFF")
        self.assertFalse(app.relay_timers.records)

    def test_off_on_and_mode_change_cancel_old_job(self):
        app=self.setup_relay()
        self.report(app);self.expire(app)
        self.report(app,relay="OFF");self.report(app)
        self.assertEqual(self.run_job(app),"skipped")
        self.assertFalse(self.payloads(app))
        self.expire(app);self.report(app,mode="decoupled")
        self.assertEqual(self.run_job(app),"skipped")
        self.assertFalse(self.payloads(app))

    def test_offline_and_maintenance_block(self):
        app=self.setup_relay()
        self.report(app);self.expire(app)
        app._on_message(None,None,msg(BASE+"/"+NAME+"/availability",b"offline",True))
        self.assertEqual(self.run_job(app),"skipped")
        self.assertFalse(self.payloads(app))
        app=self.setup_relay()
        self.report(app);self.expire(app)
        app.globals["maintenance_mode"]=True
        self.assertEqual(self.run_job(app),"skipped")
        self.assertFalse(self.payloads(app))

    def test_reconnect_requires_fresh_report_and_new_interval(self):
        app=self.setup_relay()
        self.report(app);self.expire(app)
        app.relay_timers.reset()
        self.assertEqual(self.run_job(app),"skipped")
        self.assertFalse(app.relay_timers.records)
        self.report(app,retained=True);app.relay_timers.tick()
        self.assertFalse(app.relay_timers.records)
        self.report(app)
        self.assertGreater(app.relay_timers.records[(ENTITY,"right")]["deadline"],time.monotonic()+50)
