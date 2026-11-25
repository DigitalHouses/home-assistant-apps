import json
import unittest
from copy import deepcopy
from electrica import profiles
from electrica.light_rules import parse_rule
import test_ha_native_output as native
from test_profiles import SNAP,CAP,binding,publish_profiles
from test_lab_rest_fallback import BASE,PHYSICAL,PHYSICAL_DEVICE,COORD,DEVICE,packet

TV=native.TV
MEDIA="media_player.room"

class AutoProfileTests(unittest.TestCase):
    def app(self,eid=TV,*,state="on",enabled=True,route=False):
        app,ha,registry=native.NativeLightIntegration().build([TV],route=route,physical=state.upper(),
                registry=[{"entity_id":TV,"platform":"template"},{"entity_id":MEDIA,"platform":"cast"}])
        app.globals["auto_day_night"]=enabled
        sw=app.config["rooms"][0]["switches"][0]
        sw["bindings"]["double"]=parse_rule({"assignments":[binding(eid,"current","volume" if eid==MEDIA else "toggle")]})
        app.target_catalog={eid:{**CAP,"operations":["volume"],"integration":"template"}}
        app._target_registries=([],[],[{"entity_id":TV,"platform":"template"}])
        ha.read_domain_state.return_value={"entity_id":eid,"state":state,"attributes":{
            "supported_color_modes":["color_temp"],"min_color_temp_kelvin":2200,"max_color_temp_kelvin":6500,
            "supported_features":4 if eid==MEDIA else 0,"volume_level":.4}}
        return app,ha,sw

    def transition(self,app):
        day={**deepcopy(SNAP),"mode":"day"}
        app._accept_home_profile(day,retained=True)
        app._accept_home_profile(deepcopy(SNAP))
        self.assertEqual(app._jobs.qsize(),1)
        job=app._jobs.get_nowait()
        app._adapt_home_profile(job[6])
        app._jobs.task_done()

    def test_native_on_updates_off_does_not(self):
        for state in ("on","off","unavailable"):
            app,ha,_=self.app(state=state)
            self.transition(app)
            if state=="on":
                ha.execute.assert_called_once_with({"service":"light.turn_on","target":{"entity_id":[TV]},
                                                    "data":{"brightness_pct":30,"color_temp_kelvin":2700}})
                self.assertEqual(app.event_log.snapshot()["rows"][0]["targets"][TV]["status"],"accepted")
            else:ha.execute.assert_not_called()

    def test_no_initial_replay_duplicate_or_disabled_auto_transition(self):
        app,ha,_=self.app()
        app._accept_home_profile(deepcopy(SNAP),retained=True)
        app._accept_home_profile(deepcopy(SNAP))
        self.assertTrue(app._jobs.empty())
        app._accept_home_profile({**SNAP,"mode":"day"},retained=True)
        self.assertTrue(app._jobs.empty())
        app.globals["auto_day_night"]=False
        app._accept_home_profile(deepcopy(SNAP))
        self.assertTrue(app._jobs.empty())
        ha.execute.assert_not_called()

    def test_conflict_and_disabled_binding(self):
        app,ha,sw=self.app()
        sw["bindings"]["single"]=parse_rule({"assignments":[binding(TV,"day")]})
        self.assertEqual(profiles.adaptation_targets(app.config),([], [TV]))
        self.transition(app)
        ha.execute.assert_not_called()
        sw["disabled_actions"]=["single"]
        self.assertEqual(profiles.adaptation_targets(app.config),([TV],[]))

    def test_media_only_volume_active(self):
        for state in ("playing","idle","off","standby"):
            app,ha,_=self.app(MEDIA,state=state)
            self.transition(app)
            if state in ("playing","idle"):
                ha.execute_media.assert_called_once_with(MEDIA,"volume",{"volume_level":.15})
            else:ha.execute_media.assert_not_called()
            ha.execute.assert_not_called()

    def test_stale_job_and_maintenance(self):
        app,ha,_=self.app()
        app._accept_home_profile({**SNAP,"mode":"day"},retained=True)
        app._accept_home_profile(deepcopy(SNAP))
        job=app._jobs.get_nowait()
        app._accept_home_profile({**SNAP,"mode":"day"})
        app._adapt_home_profile(job[6])
        ha.execute.assert_not_called()
        app.globals["maintenance_mode"]=True
        app._adapt_home_profile(app._home_profile)
        ha.execute.assert_not_called()

    def test_z2m_params_only_and_off_skip(self):
        for state in ("on","off"):
            app,ha,_=self.app(PHYSICAL,state=state,route=True)
            route=app.config["light_routes"][PHYSICAL]
            route["features"]["brightness"]={"value_min":0,"value_max":254}
            dev=deepcopy(PHYSICAL_DEVICE)
            dev["definition"]["exposes"][0]["features"].append(
                {"property":"brightness","type":"numeric","access":7,"value_min":0,"value_max":254})
            app._on_message(None,None,packet(BASE+"/bridge/devices",[{"type":"Coordinator","ieee_address":COORD},DEVICE,dev],True))
            app.target_catalog[PHYSICAL]={"brightness":True}
            self.transition(app)
            messages=[json.loads(body) for topic,body,_ in app.client.published if topic.endswith("/set")]
            self.assertEqual(messages,[{"brightness":76}] if state=="on" else [])
            ha.execute.assert_not_called()

    def test_group_requires_all_members_online_fresh_on(self):
        route={"base_topic":BASE,"members":[{"friendly_name":"a"},{"friendly_name":"b"}]}
        net={"states":{"a":{"state":"ON"},"b":{"state":"ON"}}}
        avail={(BASE,"a"):"online",(BASE,"b"):"online"}
        fresh={(BASE,"a","state"),(BASE,"b","state")}
        self.assertTrue(profiles.group_already_on(route,net,avail,fresh,{}))
        self.assertFalse(profiles.group_already_on(route,net,avail,fresh-{(BASE,"a","state")},{}))
        self.assertFalse(profiles.group_already_on(route,net,avail,fresh,{(BASE,"b"):{"value":"OFF"}}))
        net["states"]["b"]["state"]="OFF"
        self.assertFalse(profiles.group_already_on(route,net,avail,fresh,{}))

    def test_worker_executes_normalized_transition_job(self):
        from unittest.mock import Mock
        app,ha,_=self.app()
        app._accept_home_profile({**SNAP,"mode":"day"},retained=True)
        app._accept_home_profile(deepcopy(SNAP))
        ha.execute.side_effect=lambda _:app._stop.set()
        app._run_actions()
        self.assertEqual(app._jobs.unfinished_tasks,0)
        ha.execute.assert_called_once()

    def test_old_native_shadow_does_not_block_forever(self):
        import time
        app,ha,_=self.app()
        app._ha_shadows[TV]={"state":"on","at":time.monotonic()-120}
        self.transition(app)
        ha.execute.assert_called_once()


    def test_canonical_topics_in_any_order_and_no_profile_edit_transition(self):
        from types import SimpleNamespace
        app,ha,_=self.app()
        def state(value,retain=False):
            app._on_message(None,None,SimpleNamespace(topic=profiles.STATE_TOPIC,payload=value,retain=retain))
        state(b"off",True)
        publish_profiles(app,mode=False)
        self.assertTrue(app._jobs.empty())
        publish_profiles(app,mode=False,values={"day":SNAP["day"],"night":{**SNAP["night"],"brightness":40}})
        self.assertTrue(app._jobs.empty())
        state(b"on")
        self.assertEqual(app._jobs.qsize(),1)
        state(b"on")
        self.assertEqual(app._jobs.qsize(),1)
        job=app._jobs.get_nowait()
        app._adapt_home_profile(job[6])
        self.assertEqual(ha.execute.call_args.args[0]["data"]["brightness_pct"],40)
        state(b"")
        state(b"off")
        self.assertTrue(app._jobs.empty())
