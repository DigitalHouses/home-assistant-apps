"""Global profile references do not duplicate the home's parameter store."""
import unittest
from copy import deepcopy
from electrica import profiles
from electrica.catalog import CatalogError
from electrica.light_rules import parse_rule
from electrica.ingress import validate_assignment
from electrica.ingress_catalog import normalize
import test_ha_native_output as native
from test_ha_native_output import TV, LAB
from test_lab_rest_fallback import packet

SNAP={"schema":1,"mode":"night",
      "day":{"brightness_pct":100,"color_temp_kelvin":4300,"rgb_color":[255,255,255],"color_mode":"cct","volume_pct":40},
      "night":{"brightness_pct":30,"color_temp_kelvin":2700,"rgb_color":[255,100,20],"color_mode":"cct","volume_pct":15}}
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
        self.assertEqual(profiles.resolve({"profile":"current"},{"rgb":True},SNAP,"light"),{"rgb_color":[255,100,20]})
        self.assertEqual(profiles.resolve({"profile":"current"},{"operations":["volume"]},SNAP,"media_player"),{"volume_pct":15})
        for bad in ({"profile":"foo"},{"profile":"day","brightness_pct":20},{"profile":False}):
            with self.assertRaises(CatalogError):profiles.source(bad)

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
        self.assertEqual(profiles.validate_snapshot(SNAP),SNAP)
        for change in ({"mode":"unknown"},{"schema":True},{"day":{}},{"night":{**SNAP["night"],"brightness_pct":0}}):
            with self.assertRaises(CatalogError):profiles.validate_snapshot({**SNAP,**change})
        app,ha,_=native.NativeLightIntegration().build([TV,LAB],tv="off",lab="off")
        app.target_catalog={TV:CAP}
        app.config["rooms"][0]["switches"][0]["bindings"]["double"]=parse_rule({"assignments":[
            binding(TV,"current"),{"entity_id":LAB,"operation":"on","data":{}}]})
        app._on_message(None,None,packet(profiles.TOPIC,SNAP,True))
        self.assertEqual(app._home_profile["mode"],"night")
        app._on_message(None,None,packet(profiles.TOPIC,{"mode":"bad"},True))
        self.assertIsNone(app._home_profile)
        results,_=native.NativeLightIntegration().run_button(app)
        self.assertEqual(results[0]["state"],"partial")
        ha.execute.assert_called_once_with({"service":"light.turn_on","target":{"entity_id":[LAB]},"data":{}})

    def test_worker_resolves_profiles_before_existing_engine(self):
        for ref,expected in (("day",100),("night",30),("current",30)):
            app,ha,_=native.NativeLightIntegration().build([TV],tv="off")
            app.target_catalog={TV:CAP}
            app.config["rooms"][0]["switches"][0]["bindings"]["double"]=parse_rule({"assignments":[binding(TV,ref)]})
            app._on_message(None,None,packet(profiles.TOPIC,SNAP,True))
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
