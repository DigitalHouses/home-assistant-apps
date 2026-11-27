import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from actions.event_log import EventLog
from actions.ingress import export_log
from actions import profile_feedback
from actions.mqtt_lights import _xy

EID="light.test"
ROUTE=("z2m","zigbee2mqtt","test")
HA=("ha",EID)

class PersistentLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"log.sqlite3"
    def test_restart_preserves_confirmed_and_interrupts_pending_without_replay(self):
        log=EventLog(self.path)
        first=log.press("global","mode","night",[EID])
        log.sent(first,EID,ROUTE,"on","on",accepted_only=True,parameters={"brightness_pct":15},expected_parameters={"brightness":38})
        log.observe_light(ROUTE,{"state":"ON","brightness":38})
        second=log.press("global","mode","day",[EID])
        log.sent(second,EID,ROUTE,"on","on",accepted_only=True,parameters={"brightness_pct":100},expected_parameters={"brightness":254})
        third=log.press("global","mode","queued",[EID])
        log.close()
        restored=EventLog(self.path)
        self.addCleanup(restored.close)
        feed=restored.snapshot()
        self.assertEqual(feed["storage"],"sqlite")
        self.assertEqual([r["targets"][EID]["status"] for r in feed["rows"]],["confirmed","timeout","skipped"])
        self.assertEqual(feed["rows"][0]["targets"][EID]["observed_parameters"],{"brightness_pct":15})
        self.assertEqual(restored.pending,{})
        self.assertFalse(restored.active_target(EID))
        fourth=restored.press("test","test","test")
        self.assertGreater(fourth,third)
        exported=export_log(SimpleNamespace(event_log=restored))
        self.assertEqual(exported["schema"],1)
        self.assertEqual([r["id"] for r in exported["rows"]],[fourth,third,second,first])
        self.assertTrue(all("_created" not in r for r in exported["rows"]))
    def test_count_and_age_prune_persistently(self):
        log=EventLog(self.path);log.LIMIT=3
        for _ in range(5):log.press("test","test","test")
        self.assertEqual(len(log.snapshot()["rows"]),3)
        log.close()
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM journal").fetchone()[0],3)
            db.execute("UPDATE journal SET created=0 WHERE id=(SELECT MIN(id) FROM journal)")
        log=EventLog(self.path);self.addCleanup(log.close)
        self.assertEqual(len(log.snapshot()["rows"]),2)
    def test_bad_db_does_not_prevent_control(self):
        self.path.write_bytes(b"invalid sqlite")
        with self.assertLogs("actions.event_log",level="ERROR"):
            log=EventLog(self.path)
        rid=log.press("test","test","test",[EID])
        log.sent(rid,EID,ROUTE,"off","on")
        log.observe(ROUTE,"on")
        feed=log.snapshot()
        self.assertEqual(feed["storage"],"memory")
        self.assertTrue(feed["storage_error"])
        self.assertEqual(feed["rows"][0]["targets"][EID]["status"],"confirmed")
        self.assertEqual(self.path.read_bytes(),b"invalid sqlite")

class ProfileFeedbackTests(unittest.TestCase):
    def setUp(self):self.log=EventLog()
    def send(self,expected,route=ROUTE,params=None,sent_at=None):
        rid=self.log.press("global","mode","night",[EID])
        self.log.sent(rid,EID,route,"on","on",accepted_only=True,
                      parameters=params or {"brightness_pct":40,"transition":5},
                      expected_parameters=expected,sent_at=sent_at)
        return rid
    def row(self,rid):
        return next(r["targets"][EID] for r in self.log.snapshot()["rows"] if r["id"]==rid)
    def test_z2m_cct_brightness_mode_and_rounding(self):
        rid=self.send({"brightness":102,"color_temp":370})
        for report in ({"state":"ON"},{"state":"ON","brightness":100},
            {"state":"ON","brightness":102,"color_temp":370,"color_mode":"xy"},
            {"state":"ON","brightness":200,"color_temp":370},
            {"state":"ON","brightness":102,"color_temp":200},
            {"state":"OFF","brightness":102,"color_temp":370}):
            self.log.observe_light(ROUTE,report)
            self.log.observe(ROUTE,"on")
            self.assertEqual(self.row(rid)["status"],"accepted")
        self.log.observe_light(ROUTE,{"state":"ON","brightness":101,"color_temp":371,"color_mode":"color_temp"})
        self.assertEqual(self.row(rid)["status"],"confirmed")
        self.assertEqual(self.row(rid)["observed_parameters"],{"brightness_pct":40,"color_temp_kelvin":2695})
    def test_xy_hs_and_brightness_only(self):
        xy=_xy(43,0,255)
        rid=self.send({"brightness":38,"color":xy})
        self.log.observe_light(ROUTE,{"state":"ON","brightness":38,"color":_xy(255,255,255),"color_mode":"xy"})
        self.assertEqual(self.row(rid)["status"],"accepted")
        self.log.observe_light(ROUTE,{"state":"ON","brightness":38,"color":xy,"color_mode":"xy"})
        self.assertEqual(self.row(rid)["observed_parameters"]["xy_color"],[xy["x"],xy["y"]])
        rid=self.send({"color":{"hue":359,"saturation":100}})
        self.log.observe_light(ROUTE,{"state":"ON","color":{"hue":0,"saturation":99},"color_mode":"hs"})
        self.assertEqual(self.row(rid)["status"],"confirmed")
        rid=self.send({"brightness":254})
        self.log.observe_light(ROUTE,{"state":"ON","brightness":254})
        self.assertEqual(self.row(rid)["status"],"confirmed")
    def test_ha_fresh_attributes_and_active_color_mode(self):
        now=datetime.now(timezone.utc)
        rid=self.send({"brightness_pct":40,"color_temp_kelvin":2700},HA,sent_at=now.isoformat())
        state={"entity_id":EID,"state":"on","last_updated":now.isoformat(),
               "attributes":{"brightness":102,"color_mode":"color_temp","color_temp_kelvin":2700}}
        self.log.ha_observations([state])
        self.assertEqual(self.row(rid)["status"],"accepted")
        state["last_updated"]=(now+timedelta(seconds=1)).isoformat()
        state["attributes"]["color_mode"]="rgb"
        self.log.ha_observations([state])
        self.assertEqual(self.row(rid)["status"],"accepted")
        state["attributes"]["color_mode"]="color_temp"
        self.log.ha_observations([state])
        self.assertEqual(self.row(rid)["status"],"confirmed")
        rid=self.send({"rgb_color":[43,0,255]},HA,sent_at=now.isoformat())
        state["attributes"]={"color_mode":"rgb","rgb_color":[43,0,255]}
        self.log.ha_observations([state])
        self.assertEqual(self.row(rid)["status"],"confirmed")
    def test_transition_deadline_and_supersede(self):
        with patch("actions.event_log.monotonic",return_value=10):
            first=self.send({"brightness":102})
            self.assertFalse(self.log.active_target(EID))
            second=self.send({"brightness":254})
            self.assertEqual(self.row(first)["status"],"superseded")
            self.log.observe_light(ROUTE,{"state":"ON","brightness":102})
            self.assertEqual(self.row(second)["status"],"accepted")
        with patch("actions.event_log.monotonic",return_value=101):
            self.assertEqual(self.row(second)["status"],"accepted")
        with patch("actions.event_log.monotonic",return_value=106):
            self.assertEqual(self.row(second)["status"],"timeout")
    def test_zero_off_confirms_only_off(self):
        rid=self.log.press("global","mode","night",[EID])
        self.log.sent(rid,EID,ROUTE,"on","off",parameters={"brightness_pct":0,"rgb_color":[1,2,3],"transition":5})
        self.log.observe(ROUTE,"OFF")
        target=self.row(rid)
        self.assertEqual(target["status"],"confirmed")
        self.assertEqual(target["parameters"],{"brightness_pct":0,"transition":5})
