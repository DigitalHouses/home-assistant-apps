"""Recovery uses real schedule queue and durable checkpoints, no HA/MQTT I/O."""
import unittest
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import time
from unittest.mock import patch

from actions import readiness
from actions.schedule_engine import ScheduleEngine
from actions.schedule_rules import validate_row
from actions.binding_store import validate_document
from actions.entity_options import project,render_rows
from actions.catalog import CatalogError
from test_schedules import row,sun,ID
from test_sensor_engine import TV
import test_sensor_engine as sensor_tests
from test_ingress import PROFILE

UTC=timezone.utc

class RecoveryTests(unittest.TestCase):
    def build(self,*,state="off",solar=False,catch=True):
        h=sensor_tests.SensorEngineTests()
        self.addCleanup(h.doCleanups)
        app,ha,_=h.app(target_state=state)
        tmp=TemporaryDirectory();self.addCleanup(tmp.cleanup)
        path=Path(tmp.name)/"schedule_history.json"
        engine=app.schedule_engine=ScheduleEngine(app,path)
        now=datetime.now(UTC)
        due=now.replace(second=0,microsecond=0)-timedelta(minutes=1)
        trigger={"kind":"sunset","offset_minutes":0} if solar else {"kind":"time","time":due.strftime("%H:%M")}
        r=row(trigger);r["catch_up"]=catch
        app.config["schedules"]={ID:r}
        before=due-timedelta(minutes=10)
        before_sun=sun(due+timedelta(hours=12),due) if solar else None
        after_sun=sun(due+timedelta(hours=12),due+timedelta(days=1)) if solar else None
        return h,app,ha,engine,path,now,due,before,before_sun,after_sun

    def lease(self,app,ha="on",zigbee="on",retained=False):
        r=app.readiness
        r.receive(readiness.AVAIL,b"online",True)
        payload={"session_id":"test-session","observed_at":datetime.now(UTC).isoformat(),"valid_for_seconds":20,
                 "mqtt_ready":"on","ha_ready":ha,"zigbee_ready":zigbee,"system_ready":ha}
        r.receive(readiness.LEASE,json.dumps(payload).encode(),retained)

    def checkpoint(self,app,e,before,solar):
        self.lease(app)
        e.baseline("UTC",solar,before)
        e.tick(before)
        self.assertTrue(e.recovery.saved["ha"])
        self.assertTrue(app._jobs.empty())

    def restart(self,app,path,now,solar):
        app.readiness.reset()
        e=app.schedule_engine=ScheduleEngine(app,path)
        e.baseline("UTC",solar,now)
        return e

    def test_first_install_and_retained_lease_do_not_replay(self):
        h,app,ha,e,path,now,due,before,bs,after=self.build()
        e.baseline("UTC",None,now)
        self.lease(app,retained=True)
        e.tick(now)
        self.assertFalse(path.exists())
        self.lease(app)
        e.tick(now)
        self.assertTrue(path.exists())
        self.assertTrue(app._jobs.empty())

    def test_restart_replays_once_and_skips_when_already_on(self):
        for state in ("off","on"):
            h,app,ha,e,path,now,due,before,bs,after=self.build(state=state)
            self.checkpoint(app,e,before,bs)
            e=self.restart(app,path,now,after)
            e.tick(now);self.assertTrue(app._jobs.empty())
            self.lease(app)
            e.tick(now)
            self.assertEqual(app._jobs.qsize(),1)
            self.assertTrue(app._jobs.queue[0][1]["recovery"])
            self.assertEqual(h.run_job(app)[0]["state"],"sent" if state=="off" else "skipped")
            self.assertEqual(ha.execute.call_count,1 if state=="off" else 0)
            e=self.restart(app,path,now+timedelta(seconds=1),after)
            self.lease(app);e.tick(now+timedelta(seconds=1))
            self.assertTrue(app._jobs.empty())

    def test_later_off_supersedes_even_without_catch_up(self):
        for catch in (True,False):
            h,app,ha,e,path,now,due,before,bs,after=self.build(state="on")
            later=due+timedelta(minutes=1)
            r=row({"kind":"time","time":later.strftime("%H:%M")},[{"entity_id":TV,"operation":"off","data":{}}])
            r.update(entity_id="schedule.later",catch_up=catch)
            app.config["schedules"][r["entity_id"]]=r
            self.checkpoint(app,e,before,None)
            e=self.restart(app,path,now,None)
            self.lease(app);e.tick(now)
            if catch:
                self.assertEqual(app._jobs.qsize(),1)
                self.assertEqual(h.run_job(app)[0]["state"],"sent")
                self.assertEqual(ha.execute.call_args.args[0]["service"],"light.turn_off")
            else:
                self.assertTrue(app._jobs.empty())
                ha.execute.assert_not_called()

    def test_known_solar_event_survives_rollover_but_missing_data_blocks(self):
        for valid in (True,False):
            h,app,ha,e,path,now,due,before,bs,after=self.build(solar=True)
            self.checkpoint(app,e,before,bs if valid else None)
            e=self.restart(app,path,now,after)
            self.lease(app);e.tick(now)
            self.assertEqual(app._jobs.qsize(),int(valid))
            if valid:self.assertEqual(h.run_job(app)[0]["state"],"sent")

    def test_gate_loss_recovery_without_process_restart(self):
        h,app,ha,e,path,now,due,before,bs,after=self.build()
        self.checkpoint(app,e,before,None)
        self.lease(app,ha="off")
        e.tick(due);self.assertTrue(app._jobs.empty())
        self.lease(app);e.tick(now)
        self.assertEqual(app._jobs.qsize(),1)
        self.assertEqual(h.run_job(app)[0]["state"],"sent")

    def test_no_replay_after_configuration_change_or_long_gap(self):
        for change in ("edit","gap","maintenance"):
            h,app,ha,e,path,now,due,before,bs,after=self.build()
            self.checkpoint(app,e,before if change!="gap" else before-timedelta(days=2),None)
            if change=="edit":app.config["schedules"][ID]["name"]="Edited"
            if change=="maintenance":app.globals["maintenance_mode"]=True
            e=self.restart(app,path,now,None)
            self.lease(app);e.tick(now)
            self.assertTrue(app._jobs.empty())

    def test_pending_recovery_blocked_after_gate_loss_or_manual_press(self):
        for change in ("gate","manual"):
            h,app,ha,e,path,now,due,before,bs,after=self.build()
            self.checkpoint(app,e,before,None)
            e=self.restart(app,path,now,None)
            self.lease(app);e.tick(now)
            self.assertEqual(app._jobs.qsize(),1)
            if change=="gate":app.readiness.reset()
            else:app.sensor_engine.manual_control([TV])
            self.assertEqual(h.run_job(app)[0]["state"],"skipped")
            ha.execute.assert_not_called()

    def test_normal_opt_in_fires_once_and_commits_before_dispatch(self):
        h,app,ha,e,path,now,due,before,bs,after=self.build(solar=True)
        due=now-timedelta(seconds=1)
        ss=sun(now+timedelta(hours=12),due)
        self.checkpoint(app,e,due-timedelta(seconds=2),ss)
        e.tick(now)
        self.assertEqual(app._jobs.qsize(),1)
        self.assertFalse(app._jobs.queue[0][1]["recovery"])
        self.assertEqual(h.run_job(app)[0]["state"],"sent")
        e=self.restart(app,path,now+timedelta(seconds=1),ss)
        self.lease(app);e.tick(now+timedelta(seconds=1))
        self.assertTrue(app._jobs.empty())

    def test_catch_up_is_optional_boolean_and_no_motion_commands(self):
        r=row();r["catch_up"]=True
        self.assertEqual(validate_document({"schema":1,"rows":[r]})["rows"],[r])
        self.assertEqual(project(PROFILE,{"switches":render_rows([r]),"_bindings_store":True})["schedules"][ID],r)
        with self.assertRaises(CatalogError):validate_row({**r,"catch_up":1})
        with self.assertRaises(CatalogError):validate_row({**r,"assignments":[{"entity_id":"cover.curtain","operation":"open","data":{}}]})
        self.assertNotIn("catch_up",validate_row(row()))

class LeaseTests(unittest.TestCase):
    def test_live_nonretained_lease_and_ttl(self):
        r=readiness.Readiness()
        payload={"session_id":"s","observed_at":datetime.now(UTC).isoformat(),"valid_for_seconds":20,
                 "mqtt_ready":"on","ha_ready":"on","zigbee_ready":"off","system_ready":"off"}
        raw=json.dumps(payload).encode()
        r.receive(readiness.AVAIL,b"online",True)
        r.receive(readiness.LEASE,raw,True)
        self.assertFalse(r.ready())
        r.receive(readiness.LEASE,raw)
        self.assertTrue(r.ready())
        self.assertFalse(r.ready(True))
        with patch("actions.readiness.time.monotonic",return_value=r.until+1):
            self.assertFalse(r.ready())
        r.receive(readiness.AVAIL,b"offline")
        r.receive(readiness.AVAIL,b"online")
        self.assertFalse(r.ready())

class RecoveryEdgeTests(unittest.TestCase):
    def test_missing_later_solar_data_suppresses_earlier_on(self):
        helper=RecoveryTests()
        self.addCleanup(helper.doCleanups)
        h,app,ha,e,path,now,due,before,bs,after=helper.build()
        later=row({"kind":"sunrise","offset_minutes":20},[{"entity_id":TV,"operation":"off","data":{}}])
        later.update(entity_id="schedule.sun",catch_up=False)
        app.config["schedules"][later["entity_id"]]=later
        helper.checkpoint(app,e,before,None)
        e=helper.restart(app,path,now,None)
        helper.lease(app);e.tick(now)
        self.assertTrue(app._jobs.empty())

    def test_positive_solar_offset_after_midnight_and_restart(self):
        helper=RecoveryTests()
        self.addCleanup(helper.doCleanups)
        h,app,ha,e,path,now,due,before,bs,after=helper.build(solar=True)
        event=datetime(2026,11,25,23,55,tzinfo=UTC)
        start=event-timedelta(minutes=10)
        finish=event+timedelta(minutes=30)
        r=app.config["schedules"][ID]
        r["trigger"]={"kind":"sunset","offset_minutes":20}
        helper.checkpoint(app,e,start,sun(event+timedelta(hours=12),event))
        e=helper.restart(app,path,finish,sun(event+timedelta(hours=12),event+timedelta(days=1)))
        helper.lease(app);e.tick(finish)
        self.assertEqual(app._jobs.qsize(),1)
        self.assertEqual(app._jobs.queue[0][1]["due"],event+timedelta(minutes=20))
