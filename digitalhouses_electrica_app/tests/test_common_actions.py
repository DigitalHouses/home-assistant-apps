"""Common actions share the real dispatch worker and validate source identity."""
import unittest
from copy import deepcopy
from datetime import datetime,timezone
import json
from unittest.mock import Mock

from electrica import common_rules,cover_rules
from electrica.common_engine import COMMAND_TOPIC
from electrica.light_rules import parse_rule
from electrica.control import light_commands
from electrica.binding_store import validate_document
from electrica.entity_options import project,render_rows,parse_rows
from electrica.ingress import save_schedule,delete_schedule,revision
from electrica.catalog import CatalogError
from test_sensor_engine import TV
import test_sensor_engine as sensor_tests
import test_schedules as schedule_tests
import test_cover as cover_tests
from test_ingress import PROFILE
from test_lab_rest_fallback import BASE,NAME,packet,PHYSICAL

ID="common_action.leave"

def row(assignments=None):
    return {"entity_id":ID,"name":"Уход из дома","enabled":True,
            "assignments":assignments if assignments is not None else [{"entity_id":TV,"operation":"off","data":{}}]}

def ref():
    return {"entity_id":ID,"operation":"run","data":{}}

class CommonActionTests(unittest.TestCase):
    def build(self,*,state="on",physical=False):
        h=sensor_tests.SensorEngineTests()
        self.addCleanup(h.doCleanups)
        app,ha,e=h.app(eid=PHYSICAL if physical else TV,physical=physical,target_state=state)
        app.config["common_actions"]={ID:row([{"entity_id":PHYSICAL,"operation":"off","data":{}}] if physical else None)}
        return h,app,ha

    def test_roundtrip_and_reference_validation(self):
        r=row()
        s=schedule_tests.row(assignments=[ref()])
        self.assertEqual(validate_document({"schema":1,"rows":[r,s]})["rows"],[r,s])
        cfg=project(PROFILE,{"switches":render_rows([r,s]),"_bindings_store":True})
        self.assertEqual(cfg["common_actions"],{ID:r})
        self.assertEqual(cfg["schedules"],{s["entity_id"]:s})
        self.assertEqual(cfg["orphan_bindings"],[])
        self.assertEqual(common_rules.reference(light_commands({"bindings":{"single":parse_rule({"assignments":[ref()]})},"fingerprint":{"actions":["single"]}},"single")),ID)
        for bad in ([ref(),*r["assignments"]],[{**ref(),"data":None}],[{**ref(),"operation":"off"}]):
            with self.assertRaises(CatalogError):parse_rule({"assignments":bad})
        for bad in ([ref()],[{"entity_id":TV,"operation":"toggle"}]):
            with self.assertRaises(CatalogError):common_rules.validate_row(row(bad))
        from electrica.schedule_rules import validate_row
        with self.assertRaises(CatalogError):validate_row({**s,"catch_up":True})

    def test_ingress_executes_native_and_z2m_through_existing_worker(self):
        for physical in (False,True):
            h,app,ha=self.build(physical=physical)
            app.common_engine.enqueue(ID,{"kind":"ingress"})
            self.assertEqual(h.run_job(app)[0]["state"],"sent")
            if physical:
                self.assertTrue(any(json.loads(b)=={"state":"OFF"} for t,b,_ in app.client.published if t.endswith("/set")))
                ha.execute.assert_not_called()
            else:
                ha.execute.assert_called_once_with({"service":"light.turn_off","target":{"entity_id":[TV]},"data":{}})

    def test_key_reference_rechecks_original_binding(self):
        for changed in (False,True):
            h,app,ha=self.build()
            sw=app.config["rooms"][0]["switches"][0]
            sw["bindings"]["double"]=parse_rule({"assignments":[ref()]})
            app._on_message(None,None,packet(BASE+"/"+NAME,{"action":"double"}))
            self.assertEqual(app._jobs.qsize(),1)
            if changed:sw["bindings"].pop("double")
            self.assertEqual(h.run_job(app)[0]["state"],"skipped" if changed else "sent")
            self.assertEqual(ha.execute.call_count,0 if changed else 1)

    def test_schedule_reference_rechecks_parent(self):
        for changed in (False,True):
            h,app,ha=self.build()
            s=schedule_tests.row(assignments=[ref()])
            app.config["schedules"]={s["entity_id"]:s}
            schedule_tests.ScheduleTests().queue_now(app.schedule_engine,s)
            if changed:s["enabled"]=False
            self.assertEqual(h.run_job(app)[0]["state"],"skipped" if changed else "sent")
            self.assertEqual(ha.execute.call_count,0 if changed else 1)

    def test_disabled_changed_or_missing_common(self):
        h,app,ha=self.build()
        app.common_engine.enqueue(ID,{"kind":"ingress"})
        app.config["common_actions"][ID]["enabled"]=False
        self.assertEqual(h.run_job(app)[0]["state"],"skipped")
        with self.assertRaises(CatalogError):app.common_engine.enqueue(ID,{"kind":"ingress"})
        with self.assertRaises(CatalogError):app.common_engine.enqueue("common_action.missing",{"kind":"ingress"})
        ha.execute.assert_not_called()

    def test_cover_guard_union_applies_to_common_commands(self):
        for window in ("on","off"):
            app,ha=cover_tests.CoverTests().build(op="open",sensor=window)
            app.target_catalog={cover_tests.C:{"state":"closed"}}
            r=row([{"entity_id":cover_tests.C,"operation":"open","data":{"window_sensors":[cover_tests.W]}}])
            app.config["common_actions"]={ID:r}
            self.assertEqual(cover_rules.guard_ids(app.config,cover_tests.C),[cover_tests.W])
            app.common_engine.enqueue(ID,{"kind":"ingress"})
            self.assertEqual(sensor_tests.SensorEngineTests().run_job(app)[0]["state"],"sent" if window=="off" else "skipped")
            if window=="on":ha.execute_cover.assert_not_called()

    def test_mqtt_no_retained_duplicates_stale_or_unknown_commands(self):
        h,app,ha=self.build()
        request={"entity_id":ID,"request_id":"one","issued_at":datetime.now(timezone.utc).isoformat()}
        e=app.common_engine
        raw=json.dumps(request).encode()
        self.assertIsNone(e.receive(raw,True))
        self.assertIsNone(e.receive(json.dumps({**request,"issued_at":"2000-01-01T00:00:00+00:00"}).encode()))
        app._on_message(None,None,packet(COMMAND_TOPIC,request))
        app._on_message(None,None,packet(COMMAND_TOPIC,request))
        self.assertEqual(app._jobs.qsize(),1)
        self.assertEqual(h.run_job(app)[0]["state"],"sent")
        self.assertIsNone(e.receive(raw))
        self.assertEqual(ha.execute.call_count,1)

    def test_save_delete_existing_store_and_revision(self):
        h,app,ha=self.build()
        app.options=Mock()
        app.options.read.return_value={"switches":render_rows([]),"_bindings_store":True}
        r=row()
        save_schedule(app,{"revision":revision([]),"config":r},common=True)
        opts=app.options.write.call_args.args[0]
        self.assertEqual(parse_rows(opts),[r])
        self.assertEqual(app.config["common_actions"],{ID:r})
        app.options.read.return_value=opts
        delete_schedule(app,{"revision":revision([r]),"entity_id":ID},common=True)
        self.assertNotIn("common_actions",app.config)
