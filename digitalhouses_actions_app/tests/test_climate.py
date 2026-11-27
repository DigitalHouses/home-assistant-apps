"""Climate operations use HA capabilities, live state and shared Engine."""
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from actions import climate_rules as cr
from actions.catalog import CatalogError
from actions.control import light_commands
from actions.event_log import EventLog
from actions.ingress import validate_assignment
from actions.ingress_catalog import target_catalog
from actions.light_rules import parse_rule
from test_ingress import REGISTRIES, STATES, PROFILE
import test_ha_native_output as native
from test_lab_rest_fallback import NAME, BASE, LAB

C="climate.bedroom"
def state(mode="heat", temp=21, flags=385, modes=None):
    return {"entity_id":C,"state":mode,"attributes":{
        "supported_features":flags,"hvac_modes":modes if modes is not None else ["off","heat","cool"],
        "min_temp":16,"max_temp":30,"target_temp_step":0.5,"temperature":temp,
        "friendly_name":"Климат спальни"}}

def assignment(op="toggle",data=None):
    return {"entity_id":C,"operation":op,"data":data or {}}

def rule(op="toggle",data=None):
    return parse_rule({"assignments":[assignment(op,data)]})


class ClimateTests(unittest.TestCase):
    def test_capabilities_flags_modes_and_temperature_units(self):
        attrs=state()["attributes"]
        self.assertEqual(cr.capabilities(attrs,"°C")["operations"],["toggle","on","off","hvac_mode","temperature"])
        self.assertEqual(cr.capabilities(attrs,None)["operations"],["toggle","on","off","hvac_mode"])
        self.assertEqual(cr.capabilities(state(flags=2)["attributes"],"°C")["operations"],["hvac_mode"])
        self.assertEqual(cr.capabilities(state(modes=["heat"])["attributes"],"°C")["operations"],["hvac_mode","temperature"])
        regs=deepcopy(REGISTRIES)
        regs[2].append({"entity_id":C,"device_id":"target"})
        catalog=target_catalog(regs,STATES+[state()],PROFILE,"°C")
        self.assertEqual(catalog[C]["name"],"Климат спальни")
        validate_assignment(assignment("temperature",{"temperature":22.5,"temperature_unit":"°C"}),catalog)
        for value in (31,22.3,True):
            with self.assertRaises(CatalogError):
                validate_assignment(assignment("temperature",{"temperature":value,"temperature_unit":"°C"}),catalog)
        with self.assertRaises(CatalogError):
            validate_assignment(assignment("hvac_mode",{"hvac_mode":"dry"}),catalog)
        with self.assertRaises(CatalogError):
            validate_assignment(assignment("temperature",{"temperature":22,"temperature_unit":"°F"}),catalog)

    def test_explicit_toggle_and_no_implicit_hvac_mode(self):
        self.assertEqual(cr.plan("toggle",{},state("off")),("on",{},"active"))
        self.assertEqual(cr.plan("toggle",{},state()),("off",{},"off"))
        self.assertEqual(cr.plan("hvac_mode",{"hvac_mode":"cool"},state()),("hvac_mode",{"hvac_mode":"cool"},"cool"))
        self.assertEqual(cr.plan("temperature",{"temperature":22.5,"temperature_unit":"°C"},state(),"°C"),
                         ("temperature",{"temperature":22.5},"temperature:22.5"))
        for s in (state("unavailable"),state("unknown"),state(flags=1)):
            with self.assertRaises(CatalogError):cr.plan("toggle",{},s)
        with self.assertRaises(CatalogError):cr.plan("temperature",{"temperature":22,"temperature_unit":"°C"},state(),"°F")
        with self.assertRaises(CatalogError):cr.plan("temperature",{"temperature":22,"temperature_unit":"°C"},state("heat_cool",flags=387,modes=["off","heat_cool"]),"°C")

    def test_strict_parameters_and_mixed_batch(self):
        for op,data in (("on",{"hvac_mode":"heat"}),("hvac_mode",{"hvac_mode":"arbitrary"}),
                        ("temperature",{"temperature":22}),("temperature",{"temperature":float("nan"),"temperature_unit":"°C"})):
            with self.assertRaises(CatalogError):rule(op,data)
        r=parse_rule({"assignments":[assignment("hvac_mode",{"hvac_mode":"heat"}),
                                      {"entity_id":"light.bra","operation":"off","data":{}}]})
        commands=light_commands({"fingerprint":{"actions":["single"]},"bindings":{"single":r}},"single")
        self.assertEqual(commands,[{"service":"climate.set_hvac_mode","target":{"entity_id":[C]},"data":{"hvac_mode":"heat"}},
                                   {"service":"light.turn_off","target":{"entity_id":["light.bra"]}}])

    def test_worker_uses_live_capability_and_explicit_service(self):
        for mode,expected in (("off","on"),("heat","off"),("unknown",None)):
            app,ha,_=native.NativeLightIntegration().build([LAB],registry=[{"entity_id":C,"platform":"mqtt"}])
            app.config["rooms"][0]["switches"][0]["bindings"]["double"]=rule()
            ha.read_domain_state.return_value=state(mode)
            results,_=native.NativeLightIntegration().run_button(app)
            if expected:
                self.assertEqual(results[0]["state"],"sent")
                ha.execute_climate.assert_called_once_with(C,expected,{})
            else:
                self.assertEqual(results[0]["state"],"skipped")
                ha.execute_climate.assert_not_called()

    def test_temperature_rechecks_unit_and_skips_unverified_registry(self):
        for registered,unit,expected in [(True,"°C",True),(True,"°F",False),(False,"°C",False)]:
            app,ha,registry=native.NativeLightIntegration().build([LAB],registry=[{"entity_id":C}] if registered else [])
            registry.fetch_temperature_unit.return_value=unit
            app.config["rooms"][0]["switches"][0]["bindings"]["double"]=rule("temperature",{"temperature":23,"temperature_unit":"°C"})
            ha.read_domain_state.return_value=state()
            results,_=native.NativeLightIntegration().run_button(app)
            if expected:
                self.assertEqual(results[0]["state"],"sent")
                ha.execute_climate.assert_called_once_with(C,"temperature",{"temperature":23})
            else:
                self.assertEqual(results[0]["state"],"skipped")
                ha.execute_climate.assert_not_called()

    def test_log_confirmation_requires_new_matching_setpoint_or_mode(self):
        log=EventLog()
        now=datetime.now(timezone.utc)
        rid=log.press(BASE,NAME,"double",[C])
        log.sent_ha_domain(rid,C,state(),"temperature:22.5",now.isoformat())
        for s,seconds in ((state(temp=21),1),(state(temp=22.5),-1),(state("unavailable",22.5),1)):
            log.ha_observations([{**s,"last_updated":(now+timedelta(seconds=seconds)).isoformat()}])
            self.assertEqual(log.snapshot()["rows"][0]["targets"][C]["status"],"sent")
        log.ha_observations([{**state(temp=22.5),"last_updated":(now+timedelta(seconds=1)).isoformat()}])
        self.assertEqual(log.snapshot()["rows"][0]["targets"][C]["status"],"confirmed")
        rid=log.press(BASE,NAME,"double",[C])
        log.sent_ha_domain(rid,C,state("off"),"active",now.isoformat())
        log.ha_observations([{**state("heat"),"last_updated":(now+timedelta(seconds=1)).isoformat()}])
        self.assertEqual(log.snapshot()["rows"][-1]["targets"][C]["status"],"confirmed")
