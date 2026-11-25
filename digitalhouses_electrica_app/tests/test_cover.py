"""Cover assignment, guard and existing Engine integration."""
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from electrica import cover_rules as cr
from electrica.catalog import CatalogError
from electrica.control import light_commands
from electrica.event_log import EventLog
from electrica.ingress import validate_assignment
from electrica.ingress_catalog import target_catalog
from electrica.light_rules import parse_rule
from test_ingress import REGISTRIES, STATES, PROFILE
import test_ha_native_output as native
from test_lab_rest_fallback import NAME, BASE, LAB, packet

C="cover.curtain"
W="binary_sensor.window"
def state(status="closed",pos=0,flags=15):
    return {"entity_id":C,"state":status,"attributes":{"supported_features":flags,"current_position":pos}}
def window(status="off",cls="window"):
    return {"entity_id":W,"state":status,"attributes":{"device_class":cls}}
def rule(op="toggle",data=None):
    return parse_rule({"assignments":[{"entity_id":C,"operation":op,"data":data or {}}]})

class CoverTests(unittest.TestCase):
    def test_cover_validation_and_catalog(self):
        regs=deepcopy(REGISTRIES)
        regs[2].extend([{"entity_id":C,"device_id":"target"},{"entity_id":W,"device_id":"target"},
                        {"entity_id":"binary_sensor.motion","device_id":"target"}])
        catalog=target_catalog(regs,STATES+[state(),window(),{"entity_id":"binary_sensor.motion","state":"off","attributes":{"device_class":"motion"}}],PROFILE)
        self.assertEqual(set(catalog[C]["operations"]),{"toggle","open","close","stop","position"})
        self.assertNotIn("binary_sensor.motion",catalog)
        validate_assignment({"entity_id":C,"operation":"position","data":{"position":50,"window_sensors":[W]}},catalog)
        for data in ({"position":101},{"position":True},{"position":50,"window_sensors":["light.a"]},{"position":50,"service":"foo"}):
            with self.assertRaises(CatalogError):rule("position",data)
        with self.assertRaises(CatalogError):rule("on")
        self.assertEqual(light_commands({"fingerprint":{"actions":["single"]},"bindings":{"single":rule("position",{"position":35})}},"single"),
                         [{"service":"cover.set_cover_position","target":{"entity_id":[C]},"data":{"position":35}}])

    def test_guard_and_toggle(self):
        self.assertEqual(cr.plan("toggle",{},state(),{W:window()}),("open",{},"position:100"))
        self.assertEqual(cr.plan("toggle",{},state("open",70),{}),("close",{},"position:0"))
        for bad in (window("on"),window("unknown"),window("unavailable"),window("off","motion")):
            for op,data in [("open",{}),("close",{}),("toggle",{}),("position",{"position":50})]:
                with self.assertRaises(CatalogError):cr.plan(op,data,state(),{W:bad})
            self.assertEqual(cr.plan("stop",{},state("opening"),{W:bad}),("stop",{},None))
        with self.assertRaises(CatalogError):cr.plan("toggle",{},state("opening"),{})
        with self.assertRaises(CatalogError):cr.plan("close",{},state(flags=1),{})
        with self.assertRaises(CatalogError):cr.plan("open",{},state("unknown"),{})

    def test_cover_confirmation_requires_new_settled_position(self):
        log=EventLog()
        now=datetime.now(timezone.utc)
        rid=log.press(BASE,NAME,"double",[C])
        log.sent_cover(rid,C,state(),"position:50",now.isoformat())
        for status,pos,stamp in [("opening",50,1),("open",25,1),("open",50,-1)]:
            log.ha_observations([{**state(status,pos),"last_updated":(now+timedelta(seconds=stamp)).isoformat()}])
            self.assertEqual(log.snapshot()["rows"][0]["targets"][C]["status"],"sent")
        log.ha_observations([{**state("open",50),"last_updated":(now+timedelta(seconds=1)).isoformat()}])
        self.assertEqual(log.snapshot()["rows"][0]["targets"][C]["status"],"confirmed")
        stop=log.press(BASE,NAME,"double",[C])
        log.sent_cover(stop,C,state("opening"),None,now.isoformat())
        self.assertEqual(log.snapshot()["rows"][-1]["targets"][C]["status"],"accepted")

    def build(self,op="toggle",sensor="off",missing=False):
        registry=[{"entity_id":C,"platform":"mqtt"}]
        if not missing:registry.append({"entity_id":W,"platform":"mqtt"})
        app,ha,_=native.NativeLightIntegration().build([LAB],registry=registry)
        sw=app.config["rooms"][0]["switches"][0]
        sw["bindings"]["double"]=rule(op)
        # A guard saved on another (even disabled) assignment applies globally.
        sw["configured_bindings"]={"double":rule(op),"single":rule("open",{"window_sensors":[W]})}
        ha.read_cover_or_window.side_effect=lambda eid:state() if eid==C else window(sensor)
        return app,ha

    def test_existing_worker_dispatch_and_global_guard(self):
        app,ha=self.build()
        results,_=native.NativeLightIntegration().run_button(app)
        self.assertEqual(results[0]["state"],"sent")
        ha.execute_cover.assert_called_once_with(C,"open",{})
        for status in ("on","unknown","unavailable"):
            app,ha=self.build(sensor=status)
            results,_=native.NativeLightIntegration().run_button(app)
            self.assertEqual(results[0]["state"],"skipped")
            ha.execute_cover.assert_not_called()
        app,ha=self.build(missing=True)
        results,_=native.NativeLightIntegration().run_button(app)
        self.assertEqual(results[0]["state"],"skipped")
        ha.execute_cover.assert_not_called()

    def test_stop_does_not_query_missing_guard(self):
        app,ha=self.build(op="stop",missing=True)
        results,_=native.NativeLightIntegration().run_button(app)
        self.assertEqual(results[0]["state"],"sent")
        ha.read_cover_or_window.assert_called_once_with(C)
        ha.execute_cover.assert_called_once_with(C,"stop",{})
