import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

from dh_journal import Journal
from journal_events import GlobalsJournal, LOCALES
from ingress import serve

class TestJournalIntegration(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.j=Journal(Path(tmp.name)/"journal.sqlite3",product="digitalhouses_system_globals_app",locales=LOCALES)
        self.addCleanup(self.j.close)
        self.j.start("0.1.6")

    def test_transition_only(self):
        view={"mqtt_connected":False,"gates":{"mqtt_ready":False,"ha_ready":False,"zigbee_ready":False,"system_ready":False},
              "diagnostics":{"ha_ready":{"reason":"awaiting_probe"}},"zigbee_bridges":{},
              "state":{"night_mode":"off","config":{},"profiles":{}},"lifecycle":{"ha_core_state":None,"ha_uptime_seconds":None},"card":{"state":"idle"}}
        observer=GlobalsJournal(self.j)
        observer.observe(deepcopy(view))
        initial=self.j.snapshot()["count"]
        for n in range(20):
            view["lifecycle"]["ha_uptime_seconds"]=n
            observer.observe(deepcopy(view))
        self.assertEqual(self.j.snapshot()["count"],initial)
        view["mqtt_connected"]=True
        view["gates"].update(mqtt_ready=True,ha_ready=True,zigbee_ready=True,system_ready=True)
        view["lifecycle"]["ha_core_state"]="RUNNING"
        observer.observe(deepcopy(view))
        codes=[r["code"] for r in self.j.snapshot()["rows"]]
        self.assertEqual(codes.count("mqtt_connected"),1)
        self.assertEqual(codes.count("gate_ready"),4)
        self.assertEqual(codes.count("ha_core_state"),1)
        view["state"]["night_mode"]="on"
        observer.observe(deepcopy(view))
        self.assertEqual(self.j.snapshot()["rows"][-1]["code"],"night_mode_on")
        view["gates"]["ha_ready"]=False
        view["diagnostics"]["ha_ready"]["reason"]="awaiting_probe"
        observer.observe(deepcopy(view))
        count=self.j.snapshot()["count"]
        view["diagnostics"]["ha_ready"]["reason"]="ha_probe_not_confirmed"
        observer.observe(deepcopy(view))
        self.assertEqual(self.j.snapshot()["count"],count+1)
        observer.observe(deepcopy(view))
        self.assertEqual(self.j.snapshot()["count"],count+1)

    def test_ingress_assets_export_clear(self):
        class Service:
            journal=self.j
            def view(self):
                return {"state":{"config":{"timezone":"Asia/Almaty"}}}
        server=serve(Service(),host="127.0.0.1",port=0,allowed={"127.0.0.1"})
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base="http://127.0.0.1:"+str(server.server_address[1])
        with urlopen(base+"/log") as res:
            self.assertIn(b"journal.js",res.read())
            self.assertIn("text/html",res.headers["Content-Type"])
        with urlopen(base+"/journal.js") as res:
            self.assertIn(b"api/log",res.read())
        with urlopen(base+"/api/log?lang=en") as res:
            data=json.load(res)
        self.assertEqual(data["rows"][0]["code"],"app_started")
        self.assertIn("APPLICATION START",data["rows"][0]["message"])
        with urlopen(base+"/api/log/export?lang=ru") as res:
            self.assertIn("digitalhouses_system_globals_app_",res.headers["Content-Disposition"])
            self.assertIn(".log",res.headers["Content-Disposition"])
            self.assertIn("ЗАПУСК ПРИЛОЖЕНИЯ",res.read().decode())
        with self.assertRaises(HTTPError):
            urlopen(Request(base+"/api/log/clear",data=b"{}",headers={"Content-Type":"application/json"}))
        self.assertEqual(self.j.snapshot()["count"],1)
        with urlopen(Request(base+"/api/log/clear",data=b'{"confirm":true}',headers={"Content-Type":"application/json"})) as res:
            self.assertTrue(json.load(res)["ok"])
        self.assertEqual(self.j.snapshot()["rows"][0]["code"],"journal_cleared")

    def test_unauthorized_ingress(self):
        class Service:
            journal=self.j
        server=serve(Service(),host="127.0.0.1",port=0,allowed={"172.30.32.2"})
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with self.assertRaises(HTTPError) as raised:
            urlopen("http://127.0.0.1:"+str(server.server_address[1])+"/api/log")
        self.assertEqual(raised.exception.code,403)
