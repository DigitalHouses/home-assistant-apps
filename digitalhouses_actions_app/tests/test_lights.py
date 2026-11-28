from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from actions import lights
from actions.catalog import CatalogError
from actions.ingress import save_lights, revision
from test_profiles import CAP, SNAP, binding
import test_auto_profiles as auto_tests
from test_ha_native_output import TV
from actions.light_rules import parse_rule

def dt(h):
    return datetime(2026, 11, 28, tzinfo=timezone.utc)+timedelta(hours=h)

def row(dn=True, adaptive=False, color="cct"):
    return {"day_night":dn,"adaptive":adaptive,"color_source":color}

class LightsTests(TestCase):
    def test_both_seasons_reach_same_bounds(self):
        for rise,noon,setting in ((3,9,15),(6,9,12)):
            for h,k in ((rise,0),((rise+noon)/2,.5),(noon,1),((noon+setting)/2,.5),(setting,0)):
                f=lights.curve(dt(h),dt(rise),dt(noon),dt(setting))
                self.assertAlmostEqual(f,k)
                self.assertEqual(lights.adaptive_parameters(CAP,SNAP,f),{"color_temp_kelvin":round(2700+1600*k)})

    def test_bounds_and_no_other_parameters(self):
        snap=deepcopy(SNAP);snap["day"]["color_temp_kelvin"]=6000;snap["night"]["color_temp_kelvin"]=2000
        self.assertEqual(lights.adaptive_parameters(CAP,snap,0),{"color_temp_kelvin":2200})
        self.assertEqual(lights.adaptive_parameters(CAP,snap,1),{"color_temp_kelvin":6000})
        snap["night"]["color_temp_kelvin"]=None
        self.assertIsNone(lights.adaptive_parameters(CAP,snap,.5))

    def test_solar_observation_and_rollover(self):
        clock=lights.SolarClock();clock.reset("UTC")
        attrs={"next_rising":dt(6).isoformat(),"next_noon":dt(12).isoformat(),"next_setting":dt(18).isoformat()}
        clock.observe({"entity_id":"sun.sun","state":"below_horizon","attributes":attrs},dt(5))
        self.assertEqual(clock.factor(dt(5)),0)
        attrs["next_rising"]=dt(30).isoformat()
        clock.observe({"entity_id":"sun.sun","state":"above_horizon","attributes":attrs},dt(9))
        self.assertAlmostEqual(clock.factor(dt(9)),.5)
        attrs["next_noon"]=dt(36).isoformat()
        clock.observe({"entity_id":"sun.sun","state":"above_horizon","attributes":attrs},dt(15))
        self.assertAlmostEqual(clock.factor(dt(15)),.5)
        clock.observe(None)
        self.assertIsNone(clock.factor(dt(15)))

    def test_explicit_color_and_group_overlap(self):
        for bad in (row(color=None),row(adaptive=True,color="rgb")):
            with self.assertRaises(CatalogError):
                lights.validate_target(TV,bad,CAP)
        with self.assertRaises(CatalogError):
            lights.validate({TV:row(adaptive=True,color="rgb")})
        routes={TV:{"base_topic":"z","friendly_name":"a","ieee":"a"},
                "light.group":{"base_topic":"z","friendly_name":"g","kind":"group","members":[{"ieee":"a"}]}}
        self.assertEqual(lights.overlaps({TV:row(),"light.group":row()},routes),{TV,"light.group"})

    def test_ingress_save_roundtrip_and_invalid_revision(self):
        with TemporaryDirectory() as td:
            p=Path(td)/"lights.json"
            app=SimpleNamespace(_scan_lock=threading.Lock(),_mutex=threading.RLock(),
                light_settings={},_lights_path=p,target_catalog={TV:CAP},config={})
            save_lights(app,{"revision":revision({}),"lights":{TV:row(adaptive=True)}})
            self.assertEqual(lights.read(p),app.light_settings)
            with self.assertRaises(CatalogError):
                save_lights(app,{"revision":revision({}),"lights":{}})
            save_lights(app,{"revision":revision(app.light_settings),"lights":{}})
            self.assertEqual(lights.read(p),{})
            p.write_text("invalid")
            with self.assertRaises(ValueError):lights.write(p,{TV:row()})
            self.assertEqual(p.read_text(),"invalid")

    def test_no_binding_required_and_conflicting_presence_is_not_global_conflict(self):
        helper=auto_tests.AutoProfileTests()
        app,ha,sw=helper.app()
        sw["bindings"]={}
        app.config["sensor_bindings"]={"binary_sensor.room":{"enabled":True,"assignments":[
            {"entity_id":TV,"operation":"on","modes":{"day":{"enabled":True,"data":{}},"night":{"enabled":True,"data":{"profile":"night","color_source":"rgb"}}}}
        ]}}
        helper.transition(app)
        ha.execute.assert_called_once_with({"service":"light.turn_on","target":{"entity_id":[TV]},
                                            "data":{"brightness_pct":30,"color_temp_kelvin":2700}})

    def test_unselected_light_never_implicitly_adapts(self):
        helper=auto_tests.AutoProfileTests();app,ha,_=helper.app()
        app.light_settings={}
        helper.transition(app)
        ha.execute.assert_not_called()

    def test_adaptive_only_cct_no_brightness_and_no_off(self):
        helper=auto_tests.AutoProfileTests()
        for state in ("on","off","unavailable"):
            app,ha,_=helper.app(state=state,enabled=False)
            app.light_settings={TV:row(False,True)}
            app.sensor_engine.ready=True
            app.sensor_engine.states[TV]={"entity_id":TV,"state":state}
            snap={**deepcopy(SNAP),"mode":"day"}
            app._home_profile=snap
            with patch.object(app.solar_clock,"factor",return_value=.5):
                app._adapt_home_profile(snap,adaptive_only=True)
            if state=="on":
                ha.execute.assert_called_once_with({"service":"light.turn_on","target":{"entity_id":[TV]},
                    "data":{"color_temp_kelvin":3500}})
            else:ha.execute.assert_not_called()

    def test_adaptive_and_daynight_night_override(self):
        helper=auto_tests.AutoProfileTests();app,ha,_=helper.app()
        app.light_settings={TV:row(True,True)}
        app.sensor_engine.ready=True
        app.sensor_engine.states[TV]={"entity_id":TV,"state":"on"}
        app._home_profile=deepcopy(SNAP)
        with patch.object(app.solar_clock,"factor",return_value=1):
            app._adapt_home_profile(app._home_profile,adaptive_only=True)
        ha.execute.assert_called_once_with({"service":"light.turn_on","target":{"entity_id":[TV]},
            "data":{"color_temp_kelvin":2700}})

    def test_tick_only_once_per_interval(self):
        helper=auto_tests.AutoProfileTests();app,_,_=helper.app(enabled=False)
        app.light_settings={TV:row(False,True)}
        app.sensor_engine.ready=True
        app._home_profile=deepcopy(SNAP)
        with patch.object(app.solar_clock,"factor",return_value=.5),patch("actions.runtime.time.monotonic",return_value=100):
            app._tick_adaptive();app._tick_adaptive()
        self.assertEqual(app._jobs.qsize(),1)
        self.assertEqual(app._jobs.get_nowait()[3],"ADAPTIVE_CCT")
        self.assertEqual(app._next_adaptive,1900)

    def test_short_interval_takes_effect_without_restart(self):
        helper=auto_tests.AutoProfileTests();app,_,_=helper.app(enabled=False)
        app.light_settings={TV:row(False,True)}
        app.sensor_engine.ready=True
        app._home_profile=deepcopy(SNAP)
        with patch.object(app.solar_clock,"factor",return_value=.5),patch("actions.runtime.time.monotonic",return_value=100) as clock:
            app._tick_adaptive()
            app._jobs.get_nowait();app._jobs.task_done()
            clock.return_value=150
            app.set_adaptive_interval(1)
            self.assertEqual(app._next_adaptive,160)
            app._tick_adaptive()
            self.assertTrue(app._jobs.empty())
            clock.return_value=160
            app._tick_adaptive();app._tick_adaptive()
            self.assertEqual(app._jobs.qsize(),1)
            self.assertEqual(app._next_adaptive,220)

    def test_adaptive_mqtt_only_cct(self):
        import json
        from test_lab_rest_fallback import BASE, PHYSICAL, PHYSICAL_DEVICE, COORD, DEVICE, packet
        from test_mqtt_light_output import light
        from actions.light_routes import _light_features
        helper=auto_tests.AutoProfileTests()
        app,ha,_=helper.app(PHYSICAL,state="on",route=True,enabled=False)
        dev=light(PHYSICAL_DEVICE["ieee_address"],PHYSICAL_DEVICE["friendly_name"])
        app.config["light_routes"][PHYSICAL]["features"]=_light_features(dev)
        app._on_message(None,None,packet(BASE+"/bridge/devices",[{"type":"Coordinator","ieee_address":COORD},DEVICE,dev],True))
        app.target_catalog[PHYSICAL]=CAP
        app.light_settings={PHYSICAL:row(False,True)}
        app.sensor_engine.ready=True
        snap={**deepcopy(SNAP),"mode":"day"}
        app._home_profile=snap
        with patch.object(app.solar_clock,"factor",return_value=.5):
            app._adapt_home_profile(snap,adaptive_only=True)
        payloads=[json.loads(body) for topic,body,_ in app.client.published if topic.endswith("/set")]
        self.assertEqual(payloads,[{"color_temp":286}])
        ha.execute.assert_not_called()

    def test_already_matching_native_parameters_not_sent(self):
        helper=auto_tests.AutoProfileTests();app,ha,_=helper.app()
        app.light_settings={TV:row(False,True)}
        app.sensor_engine.ready=True
        app.sensor_engine.states[TV]={"entity_id":TV,"state":"on"}
        ha.read_domain_state.return_value["attributes"].update(color_mode="color_temp",color_temp_kelvin=3500)
        snap={**deepcopy(SNAP),"mode":"day"};app._home_profile=snap
        with patch.object(app.solar_clock,"factor",return_value=.5):
            app._adapt_home_profile(snap,adaptive_only=True)
        ha.execute.assert_not_called()

    def test_both_flags_day_uses_solar_cct_but_step_brightness(self):
        helper=auto_tests.AutoProfileTests();app,ha,_=helper.app()
        app.light_settings={TV:row(True,True)}
        app._accept_home_profile(deepcopy(SNAP),retained=True)
        snap={**deepcopy(SNAP),"mode":"day"};app._accept_home_profile(snap)
        job=app._jobs.get_nowait()
        with patch.object(app.solar_clock,"factor",return_value=.5):
            app._adapt_home_profile(job[6],job[5])
        ha.execute.assert_called_once_with({"service":"light.turn_on","target":{"entity_id":[TV]},
            "data":{"brightness_pct":100,"color_temp_kelvin":3500}})

    def test_explicit_adjustment_preserves_fixed_presence_owner(self):
        import test_sensor_engine as sensor_tests
        helper=sensor_tests.SensorEngineTests()
        self.addCleanup(helper.doCleanups)
        app,ha,engine=helper.app(profile=False,delay=0)
        helper.activate(app,ha,engine)
        engine.expect_profile(TV,{"brightness_pct":100})
        engine.changed(TV,sensor_tests.state(TV,"on","2026-11-26T08:01:01+00:00",brightness=255))
        self.assertIn(TV,engine.owners)
        ha.read_domain_state.return_value=deepcopy(engine.states[TV])
        engine.changed(sensor_tests.SOURCE,sensor_tests.motion("off"))
        engine.tick()
        self.assertEqual(helper.run_job(app)[0]["state"],"sent")
        self.assertEqual(ha.execute.call_args.args[0]["service"],"light.turn_off")
