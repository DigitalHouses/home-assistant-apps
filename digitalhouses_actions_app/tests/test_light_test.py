"""Engineer TEST uses the existing queue, route planning and journal."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from actions.catalog import CatalogError
from actions.ingress import live_log
import test_ha_native_output as native
from test_ha_native_output import TV, PHYSICAL, BASE, LAB, packet


class LightTest(unittest.TestCase):
    def prepare(self, eid, state="off", **kw):
        app,ha,registry=native.NativeLightIntegration().build([LAB],**kw)
        app.target_catalog[eid]={"entity_id":eid,"state":state}
        return app,ha,registry

    def run_job(self, app):
        result=[]
        def collect(**kw):
            result.append(kw)
            app._stop.set()
        app._publish_action=collect
        app._run_actions()
        app._stop.clear()
        return result[0]

    def row(self,app,rid):
        return next(r for r in app.event_log.snapshot()["rows"] if r["id"]==rid)

    def test_unassigned_ha_light_test_and_observed_confirmation(self):
        app,ha,_=self.prepare(TV,tv="off")
        old=deepcopy(app.config)
        rid=app.request_light_test(TV)
        with self.assertRaises(CatalogError):
            app.request_light_test(TV)
        self.assertEqual(self.run_job(app)["state"],"sent")
        ha.execute.assert_called_once_with({"service":"light.turn_on","target":{"entity_id":[TV]},"data":{}})
        self.assertEqual(app.config,old)
        app.options.write.assert_not_called()
        self.assertEqual(self.row(app,rid)["action"],"TEST")
        self.assertEqual(self.row(app,rid)["targets"][TV]["status"],"sent")
        app.event_log.observe(("ha",TV),"on",(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat())
        self.assertEqual(self.row(app,rid)["targets"][TV]["status"],"confirmed")
        self.assertIn(TV,live_log(app,0,None)["states"])
        ha.read_light_state.return_value="on"
        app.target_catalog[TV]["state"]="on"
        rid2=app.request_light_test(TV)
        self.assertEqual(self.run_job(app)["state"],"sent")
        self.assertEqual(ha.execute.call_args.args[0]["service"],"light.turn_off")

    def test_direct_mqtt_test_no_ha_fallback(self):
        app,ha,_=self.prepare(PHYSICAL,state="on",route=True,physical="ON")
        rid=app.request_light_test(PHYSICAL)
        self.assertEqual(self.run_job(app)["state"],"sent")
        publishes=[(t,json.loads(b),r) for t,b,r in app.client.published if t.endswith("/set")]
        self.assertEqual(publishes,[(BASE+"/led_strip/set",{"state":"OFF"},False)])
        ha.execute.assert_not_called()
        app._on_message(None,None,packet(BASE+"/led_strip",{"state":"OFF"}))
        self.assertEqual(self.row(app,rid)["targets"][PHYSICAL]["status"],"confirmed")
        self.assertEqual(live_log(app,0,None)["states"][PHYSICAL],"off")

    def test_offline_unknown_wrong_domain_and_maintenance_rejected(self):
        app,ha,_=self.prepare(PHYSICAL,route=True,avail="offline")
        for eid in (PHYSICAL,"light.missing","switch.relay",None,["light.a"]):
            with self.assertRaises(CatalogError):app.request_light_test(eid)
        app.target_catalog[TV]={"state":"unknown"}
        with self.assertRaises(CatalogError):app.request_light_test(TV)
        app.target_catalog[TV]["state"]="off"
        app.globals["maintenance_mode"]=True
        with self.assertRaises(CatalogError):app.request_light_test(TV)
        self.assertTrue(app._jobs.empty())
        ha.execute.assert_not_called()

    def test_unmapped_mqtt_not_dispatched(self):
        app,ha,_=self.prepare(PHYSICAL,route=False,registry=[{"entity_id":PHYSICAL,"platform":"mqtt"}])
        rid=app.request_light_test(PHYSICAL)
        self.assertEqual(self.run_job(app)["state"],"skipped")
        ha.execute.assert_not_called()
        self.assertEqual(self.row(app,rid)["targets"][PHYSICAL]["status"],"skipped")
        self.assertFalse(any(t.endswith("/set") for t,b,r in app.client.published))

    def test_maintenance_after_queue_blocks_dispatch(self):
        app,ha,_=self.prepare(TV)
        rid=app.request_light_test(TV)
        app.globals["maintenance_mode"]=True
        self.assertEqual(self.run_job(app)["state"],"error")
        self.assertEqual(self.row(app,rid)["targets"][TV]["status"],"skipped")
        ha.execute.assert_not_called()
