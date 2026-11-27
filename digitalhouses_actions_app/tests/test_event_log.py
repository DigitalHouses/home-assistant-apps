import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from actions.event_log import EventLog

EID="light.bra"
ROUTE=("z2m","zigbee2mqtt","bra")
class EventLogTests(unittest.TestCase):
    def setUp(self):
        self.log=EventLog()
    def row(self,rid):
        return self.log.snapshot()["rows"][[r["id"] for r in self.log.snapshot()["rows"]].index(rid)]
    def test_one_tick_then_observed_confirmation_and_cursor(self):
        rid=self.log.press("zigbee2mqtt","button","single",[EID])
        cursor=self.log.snapshot()["cursor"]
        self.log.sent(rid,EID,ROUTE,"OFF","ON")
        self.assertEqual(self.row(rid)["targets"][EID]["status"],"sent")
        self.log.observe(ROUTE,"OFF")
        self.assertEqual(self.row(rid)["targets"][EID]["status"],"sent")
        self.log.observe(ROUTE,"ON")
        feed=self.log.snapshot(cursor,self.log.generation)
        self.assertEqual(len(feed["rows"]),1)
        self.assertEqual(feed["rows"][0]["targets"][EID]["status"],"confirmed")
        self.assertEqual(feed["rows"][0]["targets"][EID]["before"],"off")
        self.assertEqual(self.log.snapshot(feed["cursor"],self.log.generation)["rows"],[])
    def test_superseded_disconnect_and_timeout(self):
        with patch("actions.event_log.monotonic",return_value=1):
            first=self.log.press("net","button","single",[EID])
            self.log.sent(first,EID,ROUTE,"off","on")
            second=self.log.press("net","button","single",[EID])
            self.log.sent(second,EID,ROUTE,"on","off")
            self.assertEqual(self.row(first)["targets"][EID]["status"],"superseded")
            self.log.observe(ROUTE,"ON")
            self.assertEqual(self.row(second)["targets"][EID]["status"],"sent")
        with patch("actions.event_log.monotonic",return_value=92):
            self.assertEqual(self.row(second)["targets"][EID]["status"],"timeout")
            self.log.observe(ROUTE,"OFF")
            self.assertEqual(self.row(second)["targets"][EID]["status"],"timeout")
            third=self.log.press("net","button","double",[EID])
            self.log.sent(third,EID,ROUTE,"on","off")
            self.log.disconnect()
            self.log.observe(ROUTE,"OFF")
            self.assertEqual(self.row(third)["targets"][EID]["status"],"timeout")
    def test_ha_requires_fresh_change(self):
        route=("ha",EID)
        rid=self.log.press("net","button","single",[EID])
        now=datetime.now(timezone.utc)
        self.log.sent(rid,EID,route,"off","on",sent_at=now.isoformat())
        self.log.observe(route,"on",(now-timedelta(seconds=1)).isoformat())
        self.assertEqual(self.row(rid)["targets"][EID]["status"],"sent")
        self.log.observe(route,"on",(now+timedelta(seconds=1)).isoformat())
        self.assertEqual(self.row(rid)["targets"][EID]["status"],"confirmed")
    def test_retention_count_age_and_reset(self):
        with patch("actions.event_log.monotonic",return_value=10):
            for i in range(520):
                rid=self.log.press("net","button","single",[EID])
                self.log.sent(rid,EID,("z2m","net",str(i)),"off","on")
            data=self.log.snapshot()
            self.assertEqual(len(data["rows"]),500)
            self.assertEqual(len(self.log.pending),500)
            self.assertEqual(data["oldest"],data["rows"][0]["id"])
        with patch("actions.event_log.monotonic",return_value=86411):
            self.assertEqual(self.log.snapshot()["rows"],[])
            self.assertEqual(self.log.pending,{})
        self.assertTrue(self.log.snapshot(100,"different")["reset"])
    def test_profile_parameters_are_requested_not_confirmed(self):
        rid=self.log.press("global","Режим дома","Профиль: Ночь",[EID])
        params={"brightness_pct":40,"rgb_color":[0,255,0],"transition":2}
        self.log.sent(rid,EID,ROUTE,"on","on",accepted_only=True,parameters=params)
        params["rgb_color"][1]=0
        self.log.observe(ROUTE,"on")
        target=self.row(rid)["targets"][EID]
        self.assertEqual(target["status"],"accepted")
        self.assertEqual(target["parameters"],{"brightness_pct":40,"rgb_color":[0,255,0],"transition":2})
        self.assertFalse(self.log.active_target(EID))

    def test_skip_never_becomes_confirmed(self):
        rid=self.log.press("net","button","single",[EID])
        self.log.skip(rid,EID,"offline")
        self.log.observe(ROUTE,"on")
        self.assertEqual(self.row(rid)["targets"][EID]["status"],"skipped")
        self.assertEqual(self.row(rid)["targets"][EID]["reason"],"offline")
