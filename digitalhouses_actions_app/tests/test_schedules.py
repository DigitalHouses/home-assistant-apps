"""Clock/solar recurrence, configuration and real shared worker integration."""
import unittest
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from copy import deepcopy
from unittest.mock import patch,Mock
import threading

from actions import schedule_rules as rules,cover_rules,profiles
from actions.catalog import CatalogError
from actions.binding_store import validate_document
from actions.entity_options import project,parse_rows,render_rows
from actions.ingress import save_schedule,delete_schedule,revision
from test_sensor_engine import TV
import test_sensor_engine as sensor_tests
import test_cover as cover_tests
from test_ingress import PROFILE

UTC=timezone.utc
ID="schedule.test"
def row(trigger=None,assignments=None):
    return {"entity_id":ID,"name":"Наружный свет","enabled":True,
            "trigger":trigger or {"kind":"time","time":"08:00"},
            "assignments":assignments if assignments is not None else [{"entity_id":TV,"operation":"on","data":{}}]}
def sun(rising,setting,status="below_horizon"):
    return {"entity_id":"sun.sun","state":status,"attributes":{"next_rising":rising.isoformat(),"next_setting":setting.isoformat()}}

class ScheduleTests(unittest.TestCase):
    def build(self,r):
        h=sensor_tests.SensorEngineTests()
        self.addCleanup(h.doCleanups)
        app,ha,e=h.app()
        app.config["schedules"]={ID:r}
        return h,app,ha,app.schedule_engine

    def queue_now(self,engine,row):
        # Inject a confirmed upcoming solar event one second before now.
        now=datetime.now(UTC)
        due=now-timedelta(seconds=1)
        row["trigger"]={"kind":"sunrise","offset_minutes":0}
        engine.baseline("UTC",sun(due,due+timedelta(hours=12)),due-timedelta(seconds=1))
        engine.tick(now)
        self.assertEqual(engine.app._jobs.qsize(),1)

    def test_roundtrip_and_validation(self):
        r=row()
        self.assertEqual(validate_document({"schema":1,"rows":[r]})["rows"],[r])
        config=project(PROFILE,{"switches":render_rows([r]),"_bindings_store":True})
        self.assertEqual(config["schedules"],{ID:r})
        self.assertEqual(config["orphan_bindings"],[])
        for bad in [{**r,"name":""},{**r,"trigger":{"kind":"time","time":"24:00"}},
                    {**r,"trigger":{"kind":"sunset","offset_minutes":721}},
                    {**r,"trigger":{"kind":"sunrise","offset_minutes":True}},
                    {**r,"assignments":[]},{**r,"assignments":[{"entity_id":TV,"operation":"toggle"}]},
                    {**r,"assignments":[{"entity_id":TV,"operation":"on","off_delay_seconds":60}]}]:
            with self.assertRaises(CatalogError):rules.validate_row(bad)

    def test_clock_timezone_and_dst(self):
        r={"kind":"time","time":"08:00"}
        day=datetime(2026,11,26,3,0,tzinfo=UTC)
        pairs=rules.clock_occurrences(r,ZoneInfo("Asia/Almaty"),day,day)
        self.assertIn(("2026-11-26",day),pairs)
        # DST spring gap is omitted; fall repeat uses fold zero only.
        spring=datetime(2026,3,29,1,0,tzinfo=UTC)
        pairs=rules.clock_occurrences({"kind":"time","time":"02:30"},ZoneInfo("Europe/Berlin"),spring,spring)
        self.assertNotIn("2026-03-29",[d for d,_ in pairs])
        fall=datetime(2026,10,25,0,30,tzinfo=UTC)
        pairs=rules.clock_occurrences({"kind":"time","time":"02:30"},ZoneInfo("Europe/Berlin"),fall,fall)
        self.assertEqual([dt for d,dt in pairs if d=="2026-10-25"],[fall])

    def test_clock_once_and_no_startup_replay(self):
        r=row();h,app,ha,e=self.build(r)
        due=datetime(2026,11,26,3,0,tzinfo=UTC)
        e.baseline("Asia/Almaty",None,due-timedelta(seconds=1))
        e.tick(due)
        self.assertEqual(app._jobs.qsize(),1)
        e.tick(due+timedelta(seconds=1))
        e.tick(due-timedelta(seconds=1));e.tick(due)
        self.assertEqual(app._jobs.qsize(),1)
        h,app,ha,e=self.build(r)
        e.baseline("Asia/Almaty",None,due+timedelta(seconds=1));e.tick(due+timedelta(seconds=2))
        self.assertTrue(app._jobs.empty())
        e.baseline("Asia/Almaty",None,due-timedelta(minutes=1));e.tick(due)
        self.assertTrue(app._jobs.empty())

    def test_solar_offset_crosses_midnight_and_rollover(self):
        event=datetime(2026,11,27,0,5,tzinfo=UTC)
        r=row({"kind":"sunrise","offset_minutes":-15})
        h,app,ha,e=self.build(r)
        due=event-timedelta(minutes=15)
        e.baseline("UTC",sun(event,event+timedelta(hours=12)),due-timedelta(seconds=1))
        e.tick(due);self.assertEqual(app._jobs.qsize(),1)
        r=row({"kind":"sunrise","offset_minutes":20})
        h,app,ha,e=self.build(r)
        e.baseline("UTC",sun(event,event+timedelta(hours=12)),event-timedelta(seconds=1))
        e.observe_sun(sun(event+timedelta(days=1),event+timedelta(hours=12)),event)
        due=event+timedelta(minutes=20)
        e.tick(due-timedelta(seconds=1));e.tick(due)
        self.assertEqual(app._jobs.qsize(),1)

    def test_unknown_sun_and_changed_solar_event_block(self):
        event=datetime(2026,11,27,5,0,tzinfo=UTC)
        r=row({"kind":"sunrise","offset_minutes":-10})
        h,app,ha,e=self.build(r)
        due=event-timedelta(minutes=10)
        e.baseline("UTC",sun(event,event+timedelta(hours=12)),due-timedelta(seconds=1))
        e.observe_sun(sun(event,event+timedelta(hours=12),"unavailable"),due)
        e.tick(due)
        self.assertTrue(app._jobs.empty())
        e.baseline("UTC",sun(event,event+timedelta(hours=12)),due-timedelta(seconds=1))
        e.observe_sun(sun(event+timedelta(minutes=1),event+timedelta(hours=12)),due)
        e.tick(due)
        self.assertTrue(app._jobs.empty())

    def test_real_worker_light_profiles_and_modified_schedule(self):
        r=row(assignments=[{"entity_id":TV,"operation":"on","data":{"profile":"current"}}])
        h,app,ha,e=self.build(r)
        self.queue_now(e,r)
        result=h.run_job(app)
        self.assertEqual(result[0]["state"],"sent")
        ha.execute.assert_called_once_with({"service":"light.turn_on","target":{"entity_id":[TV]},"data":{"brightness_pct":30}})
        h,app,ha,e=self.build(row())
        self.queue_now(e,app.config["schedules"][ID])
        app.config["schedules"][ID]["enabled"]=False
        self.assertEqual(h.run_job(app)[0]["state"],"skipped")
        ha.execute.assert_not_called()

    def test_cover_guard_union_including_disabled_schedule(self):
        r=row(assignments=[{"entity_id":cover_tests.C,"operation":"open","data":{"window_sensors":[cover_tests.W]}}])
        for window,expected in [("off","sent"),("on","skipped"),("unavailable","skipped")]:
            app,ha=cover_tests.CoverTests().build(op="open",sensor=window)
            app.sensor_engine.ready=True
            app.config["schedules"]={ID:deepcopy(r)}
            app.target_catalog={cover_tests.C:{"state":"closed"}}
            # Window protection declared in a separate disabled schedule.
            second={**deepcopy(r),"entity_id":"schedule.guard","enabled":False}
            app.config["schedules"]["schedule.guard"]=second
            app.config["schedules"][ID]["assignments"][0]["data"]={}
            self.assertEqual(cover_rules.guard_ids(app.config,cover_tests.C),[cover_tests.W])
            self.queue_now(app.schedule_engine,app.config["schedules"][ID])
            result=sensor_tests.SensorEngineTests().run_job(app)
            self.assertEqual(result[0]["state"],expected)
            if expected=="sent":ha.execute_cover.assert_called_once_with(cover_tests.C,"open",{})
            else:ha.execute_cover.assert_not_called()

    def test_save_delete_uses_existing_revision_and_store(self):
        r=row()
        h,app,ha,e=self.build(r)
        opts={"switches":render_rows([]),"_bindings_store":True}
        app.options=Mock()
        app.options.read.return_value=opts
        app._scan_lock=threading.Lock()
        save_schedule(app,{"revision":revision([]),"config":r})
        self.assertEqual(parse_rows(app.options.write.call_args.args[0]),[r])
        self.assertEqual(app.config["schedules"],{ID:r})
        opts=app.options.write.call_args.args[0]
        app.options.read.return_value=opts
        with self.assertRaises(CatalogError):delete_schedule(app,{"revision":"stale","entity_id":ID})
        delete_schedule(app,{"revision":revision([r]),"entity_id":ID})
        self.assertNotIn("schedules",app.config)

    def test_real_z2m_worker_and_unavailable_target(self):
        import json
        from test_lab_rest_fallback import PHYSICAL
        for available in (True,False):
            h=sensor_tests.SensorEngineTests()
            self.addCleanup(h.doCleanups)
            app,ha,_=h.app(eid=PHYSICAL,physical=True)
            r=row(assignments=[{"entity_id":PHYSICAL,"operation":"on","data":{}}])
            app.config["schedules"]={ID:r}
            self.queue_now(app.schedule_engine,r)
            if not available:app._light_availability.clear()
            self.assertEqual(h.run_job(app)[0]["state"],"sent" if available else "skipped")
            outgoing=[json.loads(b) for t,b,_ in app.client.published if t.endswith("/set")]
            self.assertEqual(outgoing,[{"state":"ON"}] if available else [])
            ha.execute.assert_not_called()

    def test_expired_maintenance_and_disconnect_block_dispatch(self):
        for invalid in ("expired","maintenance","disconnect"):
            h,app,ha,e=self.build(row())
            self.queue_now(e,app.config["schedules"][ID])
            if invalid=="expired":
                job=app._jobs.queue[0]
                job[1]["due"]-=timedelta(seconds=60)
            elif invalid=="maintenance":app.globals["maintenance_mode"]=True
            else:e.disconnect()
            self.assertEqual(h.run_job(app)[0]["state"],"skipped")
            ha.execute.assert_not_called()
