import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

from dh_journal import Journal
from journal_events import GlobalsJournal, LOCALES, PRODUCT_NAME, VALUE_LOCALES, ICONS
from ingress import serve

class TestJournalIntegration(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.j=Journal(Path(tmp.name)/"journal.sqlite3",product="digitalhouses_system_globals_app",product_name=PRODUCT_NAME,locales=LOCALES,value_locales=VALUE_LOCALES,icons=ICONS)
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
        self.assertEqual(data["product_name"],PRODUCT_NAME)
        self.assertEqual(data["app_version"],"0.1.6")
        self.assertEqual(data["rows"][0]["message"],"APPLICATION START · DigitalHouses System Globals v0.1.6")
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

    def test_initialization_pending_then_warning(self):
        t=[0]
        observer=GlobalsJournal(self.j,clock=lambda:t[0])
        view={"mqtt_connected":True,"gates":{"zigbee_ready":False},
              "diagnostics":{"zigbee_ready":{"reason":"awaiting_probe"}},
              "zigbee_bridges":{}, "state":{"night_mode":"off","config":{},"profiles":{}},
              "lifecycle":{"ha_core_state":None},"card":{"state":"idle"}}
        observer.observe(deepcopy(view))
        view["diagnostics"]["zigbee_ready"]["reason"]="bridge_not_ready"
        view["zigbee_bridges"]["zigbee2mqtt"]={"ready":False}
        observer.observe(deepcopy(view))
        self.assertEqual([r["level"] for r in self.j.snapshot()["rows"][-2:]],["pending","pending"])
        t[0]=21
        observer.observe(deepcopy(view))
        self.assertEqual([r["level"] for r in self.j.snapshot()["rows"][-2:]],["warning","warning"])
        count=self.j.snapshot()["count"]
        observer.observe(deepcopy(view))
        self.assertEqual(self.j.snapshot()["count"],count)
        view["gates"]["zigbee_ready"]=True
        view["zigbee_bridges"]["zigbee2mqtt"]["ready"]=True
        observer.observe(deepcopy(view))
        self.assertEqual([r["level"] for r in self.j.snapshot()["rows"][-2:]],["success","success"])

    def test_historical_translation_and_icons(self):
        from dh_journal.http import get
        # Historic 1.0.0 rows lack product_name: render without rewriting SQLite.
        self.j.record("lifecycle","app_started",version="0.1.6",journal="1.0.0")
        self.j.warning("gate_not_ready",gate="HA Ready",reason="ha_probe_not_confirmed")
        self.j.info("night_mode_off")
        self.j.info("ha_core_state",state="RUNNING")
        raw=self.j.snapshot()
        ru=get(self.j,"/api/log?lang=ru","Asia/Almaty")[0]
        en=get(self.j,"/api/log?lang=en","Asia/Almaty")[0]
        self.assertEqual(ru["rows"][1]["message"],"ЗАПУСК ПРИЛОЖЕНИЯ · DigitalHouses System Globals v0.1.6")
        self.assertEqual(en["rows"][1]["message"],"APPLICATION START · DigitalHouses System Globals v0.1.6")
        self.assertEqual(ru["rows"][2]["message"],"HA Ready → OFF · проверка HA не подтверждена")
        self.assertEqual(en["rows"][2]["message"],"HA Ready → OFF · HA probe not confirmed")
        self.assertEqual(ru["rows"][3]["icon"],"☀️")
        self.assertEqual(ru["rows"][3]["message"],"Дневной режим включён")
        self.assertEqual(en["rows"][3]["message"],"Day mode enabled")
        self.assertEqual(ru["rows"][4]["message"],"HA Core · работает")
        self.assertEqual(en["rows"][4]["message"],"HA Core · running")
        self.assertEqual(self.j.snapshot(),raw)
        text=self.j.export("ru","Asia/Almaty")[1].decode()
        self.assertIn("☀️ Дневной режим включён",text)
        self.assertNotIn("ℹ️ ☀️",text)
        self.assertIn('"journal":"1.0.0"',text)

    def test_ram_clear_http_conflict(self):
        self.j.db.close()
        self.j.info("night_mode_off")
        class Service:
            journal=self.j
            def view(self):
                return {"state":{"config":{"timezone":"Asia/Almaty"}}}
        server=serve(Service(),host="127.0.0.1",port=0,allowed={"127.0.0.1"})
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base="http://127.0.0.1:"+str(server.server_address[1])
        with urlopen(base+"/api/log") as res:
            self.assertFalse(json.load(res)["can_clear"])
        with self.assertRaises(HTTPError) as raised:
            urlopen(Request(base+"/api/log/clear",data=b'{"confirm":true}',headers={"Content-Type":"application/json"}))
        self.assertEqual(raised.exception.code,409)
        self.assertEqual(self.j.snapshot()["rows"][-1]["code"],"night_mode_off")

    def test_unauthorized_ingress(self):
        class Service:
            journal=self.j
        server=serve(Service(),host="127.0.0.1",port=0,allowed={"172.30.32.2"})
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with self.assertRaises(HTTPError) as raised:
            urlopen("http://127.0.0.1:"+str(server.server_address[1])+"/api/log")
        self.assertEqual(raised.exception.code,403)
