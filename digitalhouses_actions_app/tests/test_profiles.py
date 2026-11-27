"""Global profile references do not duplicate the home's parameter store."""
import unittest
from copy import deepcopy
from actions import profiles
from actions.catalog import CatalogError
from actions.light_rules import parse_rule
from actions.ingress import validate_assignment
from actions.ingress_catalog import normalize
import test_ha_native_output as native
from test_ha_native_output import TV, LAB
from test_lab_rest_fallback import packet

BASE_PROFILE={"brightness":None,"color_temp_kelvin":None,"rgb_color":None,
              "volume":None,
              "transition_seconds":None,"voice_notifications_enabled":None,
              "noncritical_sound_notifications_enabled":None}
SNAP={"mode":"night",
      "day":{**BASE_PROFILE,"brightness":100,"color_temp_kelvin":4300,"volume":40},
      "night":{**BASE_PROFILE,"brightness":30,"color_temp_kelvin":2700,"volume":15}}
def publish_profiles(app,mode=True,values=None):
    app._on_message(None,None,packet(profiles.PROFILES_TOPIC,values if values is not None else {k:SNAP[k] for k in ("day","night")},True))
    if mode:
        from types import SimpleNamespace
        app._on_message(None,None,SimpleNamespace(topic=profiles.STATE_TOPIC,payload=b"on",retain=True))
CAP={"brightness":True,"cct":True,"rgb":True,"min_kelvin":2200,"max_kelvin":6500}
def binding(eid,ref,op="toggle"):
    return {"entity_id":eid,"operation":op,"data":{"profile":ref}}

class ProfileTests(unittest.TestCase):
    def test_global_reference_is_independent_of_mode_and_has_no_local_data(self):
        self.assertEqual(profiles.resolve({"profile":"day"},CAP,SNAP,"light"),
                         {"brightness_pct":100,"color_temp_kelvin":4300})
        self.assertEqual(profiles.resolve({"profile":"current"},CAP,SNAP,"light"),
                         {"brightness_pct":30,"color_temp_kelvin":2700})
        snap=deepcopy(SNAP);snap["mode"]="day"
        self.assertEqual(profiles.resolve({"profile":"night"},CAP,snap,"light")["brightness_pct"],30)
        self.assertEqual(profiles.resolve({"profile":"current"},{"brightness":True},SNAP,"light"),{"brightness_pct":30})
        self.assertEqual(profiles.resolve({"profile":"current"},{"brightness":True,"rgb":True},SNAP,"light"),{"brightness_pct":30})
        rgb={**SNAP,"night":{**SNAP["night"],"rgb_color":[255,100,20],"color_temp_kelvin":None}}
        self.assertEqual(profiles.resolve({"profile":"current"},CAP,rgb,"light"),{"brightness_pct":30,"rgb_color":[255,100,20]})
        self.assertEqual(profiles.resolve({"profile":"current"},{"operations":["volume"]},SNAP,"media_player"),{"volume_pct":15})
        for bad in ({"profile":"foo"},{"profile":"day","brightness_pct":20},{"profile":False}):
            with self.assertRaises(CatalogError):profiles.source(bad)

    def test_independent_global_colors_and_dual_capability_priority(self):
        snapshot=deepcopy(SNAP)
        snapshot["night"]["rgb_color"]=[0,0,255]
        profiles.validate_profiles({k:snapshot[k] for k in ("day","night")})
        self.assertEqual(profiles.resolve({"profile":"current"},CAP,snapshot,"light"),{"brightness_pct":30,"color_temp_kelvin":2700})
        self.assertEqual(profiles.resolve({"profile":"current"},{"brightness":True,"rgb":True},snapshot,"light"),{"brightness_pct":30,"rgb_color":[0,0,255]})
        self.assertEqual(profiles.resolve({"profile":"current"},{**CAP,"rgb":False},snapshot,"light"),{"brightness_pct":30,"color_temp_kelvin":2700})

    def test_validation_and_backward_compatibility(self):
        raw={"assignments":[binding(TV,"day"),binding("media_player.speaker","night","volume")]}
        self.assertEqual(normalize(raw),raw["assignments"])
        validate_assignment(binding(TV,"current"),{TV:CAP})
        for item,cap in [(binding(TV,"day"),{}),(binding("switch.a","day"),CAP),
                         (binding(TV,"day","off"),CAP),(binding("media_player.speaker","night","play"),{})]:
            with self.assertRaises(CatalogError):validate_assignment(item,{item["entity_id"]:cap})
        old={"service":"light.turn_on","targets":[TV],"brightness_pct":40}
        self.assertEqual(normalize(old)[0]["data"],{"brightness_pct":40})

    def test_snapshot_invalidated_and_independent_commands_work(self):
        values={k:SNAP[k] for k in ("day","night")}
        self.assertEqual(profiles.validate_profiles(values),values)
        for change in ({"day":{}},{"night":{**SNAP["night"],"brightness":-1}},{"night":{**SNAP["night"],"rgb_color":[1,2,256]}}, {"night":{**SNAP["night"],"color_temp_kelvin":7000}}):
            with self.assertRaises(CatalogError):profiles.validate_profiles({**values,**change})
        app,ha,_=native.NativeLightIntegration().build([TV,LAB],tv="off",lab="off")
        app.target_catalog={TV:CAP}
        app.config["rooms"][0]["switches"][0]["bindings"]["double"]=parse_rule({"assignments":[
            binding(TV,"current"),{"entity_id":LAB,"operation":"on","data":{}}]})
        publish_profiles(app)
        self.assertEqual(app._home_profile["mode"],"night")
        publish_profiles(app,mode=False,values={"mode":"bad"})
        self.assertEqual(app._home_profile,{"mode":"night"})
        results,_=native.NativeLightIntegration().run_button(app)
        self.assertEqual(results[0]["state"],"partial")
        ha.execute.assert_called_once_with({"service":"light.turn_on","target":{"entity_id":[LAB]},"data":{}})

    def test_worker_resolves_profiles_before_existing_engine(self):
        for ref,expected in (("day",100),("night",30),("current",30)):
            app,ha,_=native.NativeLightIntegration().build([TV],tv="off")
            app.target_catalog={TV:CAP}
            app.config["rooms"][0]["switches"][0]["bindings"]["double"]=parse_rule({"assignments":[binding(TV,ref)]})
            publish_profiles(app)
            results,_=native.NativeLightIntegration().run_button(app)
            self.assertEqual(results[0]["state"],"sent")
            self.assertEqual(ha.execute.call_args.args[0]["data"]["brightness_pct"],expected)
            self.assertNotIn("profile",ha.execute.call_args.args[0]["data"])


    def test_missing_profile_allows_only_toggle_off(self):
        for current,expected in (("on","sent"),("off","skipped")):
            app,ha,_=native.NativeLightIntegration().build([TV],tv=current)
            app.target_catalog={TV:CAP}
            app.config["rooms"][0]["switches"][0]["bindings"]["double"]=parse_rule({"assignments":[binding(TV,"current")]})
            results,_=native.NativeLightIntegration().run_button(app)
            self.assertEqual(results[0]["state"],expected)
            if current=="on":ha.execute.assert_called_once_with({"service":"light.turn_off","target":{"entity_id":[TV]},"data":{}})
            else:ha.execute.assert_not_called()


    def test_fixed_references_do_not_require_mode_and_nulls_are_not_defaults(self):
        app,ha,_=native.NativeLightIntegration().build([TV],tv="off")
        app.target_catalog={TV:CAP}
        app.config["rooms"][0]["switches"][0]["bindings"]["double"]=parse_rule({"assignments":[binding(TV,"day")]})
        publish_profiles(app,mode=False)
        self.assertIsNone(app._home_profile["mode"])
        results,_=native.NativeLightIntegration().run_button(app)
        self.assertEqual(results[0]["state"],"sent")
        self.assertEqual(ha.execute.call_args.args[0]["data"]["brightness_pct"],100)
        zero={**SNAP,"day":{**BASE_PROFILE,"brightness":0,"transition_seconds":80,"volume":0}}
        self.assertEqual(profiles.resolve({"profile":"day"},{**CAP,"transition":True},zero,"light"),{"brightness_pct":0,"transition":60})
        self.assertEqual(profiles.resolve({"profile":"day"},{"operations":["volume"]},zero,"media_player"),{"volume_pct":0})
        with self.assertRaises(CatalogError):profiles.resolve({"profile":"day"},CAP,{**SNAP,"day":BASE_PROFILE},"light")

    def test_zero_brightness_does_not_turn_on_native_light(self):
        app,ha,_=native.NativeLightIntegration().build([TV],tv="off")
        app.target_catalog={TV:CAP}
        app.config["rooms"][0]["switches"][0]["bindings"]["double"]=parse_rule({"assignments":[binding(TV,"day")]})
        publish_profiles(app,values={"day":{**SNAP["day"],"brightness":0},"night":SNAP["night"]})
        results,_=native.NativeLightIntegration().run_button(app)
        self.assertEqual(results[0]["state"],"sent")
        ha.execute.assert_called_once_with({"service":"light.turn_off","target":{"entity_id":[TV]},"data":{}})

    def test_zero_native_plan_preserves_legacy_targets(self):
        call={"service":"light.turn_on","target":{"entity_id":[TV,LAB]},"data":{"brightness_pct":0}}
        plans=list(profiles.apply_zero_to_ha_plans([call],{TV}))
        self.assertEqual(plans,[{"service":"light.turn_off","target":{"entity_id":[TV]},"data":{}},
                                {"service":"light.turn_on","target":{"entity_id":[LAB]},"data":{"brightness_pct":0}}])
