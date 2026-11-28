import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import urllib.request

from core import Engine,Store,ContractError,GLOBAL,PRODUCT
from gates import HAResult,ha_probe
from discovery import (discovery,translate,projections,FIELD,LEASE,PROBE,LOOP,AVAIL,
                       DISCOVERY,SYNC,GATE_EVENT,CTRL,state_topic,PREFIX)
from lifecycle import Lifecycle
from service import Service
from ingress import serve
from dh_journal import Journal
from journal_events import LOCALES

NOW=datetime(2026,11,26,12,tzinfo=timezone.utc)

class ContractTests(unittest.TestCase):
    def test_discovery_and_independent_colors(self):
        cfg=discovery("0.1.0")
        self.assertEqual(cfg["device"]["sw_version"],"0.1.0")
        self.assertEqual(cfg["components"]["night_mode"]["command_topic"],GLOBAL+"/set")
        self.assertEqual(cfg["components"]["system_ready"]["state_topic"],LEASE)
        self.assertGreater(cfg["components"]["system_ready"]["expire_after"],0)
        self.assertEqual(cfg["components"]["night_mode_event"]["event_types"],["night_mode_on","night_mode_off"])
        for k,c in cfg["components"].items():
            self.assertEqual(c["default_entity_id"],c["platform"]+"."+PREFIX+"_"+k)
        topic,p=translate(FIELD+"night_rgb_color/set","#0000FF")
        self.assertEqual(topic,PRODUCT+"/profiles/set")
        self.assertEqual(p,{"night":{"rgb_color":[0,0,255]}})
        with tempfile.TemporaryDirectory() as t:
            e=Engine(Store(Path(t)/"state.json"))
            e.command(topic,p,NOW)
            out=e.state
            self.assertIsNone(out["profiles"]["night"]["color_temp_kelvin"])
            q=translate(FIELD+"night_color_temp_kelvin/set","3000")
            e.command(*q,NOW)
            self.assertEqual(e.state["profiles"]["night"]["rgb_color"],[0,0,255])
            self.assertEqual(e.state["profiles"]["night"]["color_temp_kelvin"],3000)
            self.assertIn("3000",[m.payload for m in projections(e.state)])
            self.assertIn("#0000FF",[m.payload for m in projections(e.state)])
            e.command(GLOBAL+"/set","on",NOW)
            active={m.topic:m.payload for m in projections(e.state)}
            self.assertEqual(active[state_topic("active_color_temp_kelvin")],"3000")
            self.assertEqual(active[state_topic("active_rgb_color")],"[0,0,255]")
            e.command(*translate(FIELD+"night_rgb_color/set",""),NOW)
            self.assertEqual(e.state["profiles"]["night"]["color_temp_kelvin"],3000)
            before=e.state
            broken=e.state
            broken["profiles"]["night"]["rgb_color"]=[1,2,300]
            value={k:broken[k] for k in ("night_mode","config","profiles")}
            with self.assertRaises(ContractError):
                e.import_settings(value,NOW)
            self.assertEqual(e.state,before)

    def test_lifecycle_disconnect_is_not_shutdown(self):
        l=Lifecycle()
        self.assertEqual(l.observe(HAResult("RUNNING",True,True),NOW),[])
        out=l.observe(HAResult(None,False,False),NOW)
        self.assertEqual([m.payload["event_type"] for m in out],["ha_connection_lost"])
        self.assertIsNone(l.values(NOW)["ha_stopped_at"])
        self.assertIsNone(l.values(NOW)["ha_uptime_seconds"])

    def test_ha_probe_actual_http_result(self):
        current={"value":"old"}
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.headers.get("Authorization")!="Bearer test":
                    self.send_error(401);return
                data={"state":"RUNNING"} if self.path=="/config" else {"state":current["value"]}
                b=json.dumps(data).encode();self.send_response(200);self.end_headers();self.wfile.write(b)
            def log_message(self,*a):pass
        h=ThreadingHTTPServer(("127.0.0.1",0),H)
        threading.Thread(target=h.serve_forever,daemon=True).start()
        self.addCleanup(h.server_close);self.addCleanup(h.shutdown)
        url=f"http://127.0.0.1:{h.server_port}"
        self.assertFalse(ha_probe(url,"test","fresh","sensor.probe").nonce_seen)
        current["value"]="fresh"
        self.assertTrue(ha_probe(url,"test","fresh","sensor.probe").nonce_seen)


@unittest.skipUnless(os.environ.get("DH_TEST_MOSQUITTO"),"isolated broker binary not configured")
class LiveService(unittest.TestCase):
    def wait(self,predicate,timeout=22):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if predicate():return
            time.sleep(.05)
        self.fail("Timed out waiting for expected live state")

    def test_gates_and_ingress_with_real_mqtt(self):
        import paho.mqtt.client as mqtt
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
            broker=subprocess.Popen([os.environ["DH_TEST_MOSQUITTO"],"-p",str(port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self.addCleanup(self.stop_proc,broker)
            def broker_up():
                try:
                    with socket.create_connection(("127.0.0.1",port),timeout=.1):return True
                except OSError:return False
            self.wait(broker_up,5)
            received=[]
            observed={"nonce":None,"ha":True,"healthy":False,"accept_nonce":False}
            actor=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,protocol=mqtt.MQTTv5)
            def onmsg(client,u,msg):
                value=msg.payload.decode()
                received.append((msg.topic,value))
                if msg.topic==PROBE and observed["accept_nonce"]:
                    observed["nonce"]=value
                if msg.topic.endswith("/bridge/request/health_check"):
                    q=json.loads(value)
                    r={"transaction":q["transaction"],"status":"ok","data":{"healthy":observed["healthy"]}}
                    client.publish(msg.topic.replace("/request/","/response/"),json.dumps(r),qos=1)
            actor.on_message=onmsg
            actor.connect("127.0.0.1",port);actor.subscribe("#",qos=1);actor.loop_start()
            self.addCleanup(actor.loop_stop);self.addCleanup(actor.disconnect)
            def pub(topic,value,retain=False):
                actor.publish(topic,value if isinstance(value,str) else json.dumps(value),qos=1,retain=retain).wait_for_publish(timeout=3)
            # Old retained on alone is not positive readiness.
            pub("DigitalHouses/Global/system_ready/state","on",True)
            pub("zigbee2mqtt/bridge/state",{"state":"online"},True)
            pub("zigbee2mqtt/bridge/info",{"version":"2.8.0"},True)
            pub("zigbee2mqtt/bridge/devices",[],True)
            pub("floor/second/zigbee/bridge/state",{"state":"online"},True)
            pub("floor/second/zigbee/bridge/info",{"version":"2.8.0"},True)
            pub("floor/second/zigbee/bridge/devices",[],True)
            pub("homeassistant/status","online",True)
            class H(BaseHTTPRequestHandler):
                def do_GET(self):
                    if not observed["ha"]:
                        self.send_error(503);return
                    v={"state":"RUNNING"} if self.path=="/config" else {"state":observed["nonce"]}
                    self.send_response(200);self.end_headers();self.wfile.write(json.dumps(v).encode())
                def log_message(self,*a):pass
            h=ThreadingHTTPServer(("127.0.0.1",0),H)
            threading.Thread(target=h.serve_forever,daemon=True).start()
            self.addCleanup(h.server_close);self.addCleanup(h.shutdown)
            journal=Journal(root/"journal.sqlite3",product="digitalhouses_system_globals_app",locales=LOCALES)
            journal.start("0.1.0")
            self.addCleanup(journal.close)
            svc=Service(Engine(Store(root/"state.json")),"0.1.0",{"require_z2m":True,"ha_url":f"http://127.0.0.1:{h.server_port}","ha_token":"test"},release_fn=lambda:"0.2.0",journal=journal)
            stop=threading.Event()
            errors=[]
            def run():
                try:svc.run("127.0.0.1",port,None,None,stop.is_set)
                except BaseException as e:errors.append(e)
            worker=threading.Thread(target=run,daemon=True);worker.start()
            def stop_service():
                stop.set();worker.join(12)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors,[])
            self.addCleanup(stop_service)
            http=serve(svc,host="127.0.0.1",port=0,allowed={"127.0.0.1"})
            self.addCleanup(http.server_close);self.addCleanup(http.shutdown)
            def cmd(topic,payload):
                req=urllib.request.Request(f"http://127.0.0.1:{http.server_port}/api/command",data=json.dumps({"topic":topic,"payload":payload}).encode(),headers={"Content-Type":"application/json"})
                with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)
            self.wait(lambda:svc.view()["gates"]["mqtt_ready"])
            self.assertFalse(svc.view()["gates"]["system_ready"])
            self.assertFalse(svc.view()["gates"]["ha_ready"])
            observed["healthy"]=True;observed["accept_nonce"]=True
            self.wait(lambda:svc.view()["gates"]["system_ready"])
            self.assertEqual(set(svc.view()["zigbee_bridges"]),{"zigbee2mqtt","floor/second/zigbee"})
            self.assertTrue(any(t==SYNC for t,v in received))
            self.assertTrue(any(t==DISCOVERY for t,v in received))
            cmd(GLOBAL+"/set","on")
            pub(GLOBAL+"/set","off")
            self.wait(lambda:svc.view()["state"]["night_mode"]=="off")
            pub("floor/second/zigbee/bridge/state",{"state":"offline"},True)
            self.wait(lambda:not svc.view()["gates"]["zigbee_ready"])
            self.assertFalse(svc.view()["gates"]["system_ready"])
            cmd(GLOBAL+"/set","on")
            self.assertEqual(svc.view()["state"]["night_mode"],"on")
            pub("floor/second/zigbee/bridge/state",{"state":"online"},True)
            pub("floor/second/zigbee/bridge/info",{"version":"2.8.0"},True)
            pub("floor/second/zigbee/bridge/devices",[],True)
            self.wait(lambda:svc.view()["gates"]["system_ready"])
            observed["ha"]=False
            pub("homeassistant/status","offline",True)
            self.wait(lambda:not svc.view()["gates"]["ha_ready"])
            self.assertFalse(svc.view()["gates"]["system_ready"])
            observed["ha"]=True
            pub("homeassistant/status","online",True)
            self.wait(lambda:svc.view()["gates"]["system_ready"])
            cmd(CTRL+"refresh","PRESS")
            self.wait(lambda:svc.view()["card"]["state"]=="success",28)
            cmd(CTRL+"check_updates","PRESS")
            self.wait(lambda:svc.view()["latest_version"]=="0.2.0")
            self.stop_proc(broker)
            self.wait(lambda:not svc.view()["mqtt_connected"],10)
            cmd(GLOBAL+"/set","off")
            self.assertEqual(svc.view()["state"]["night_mode"],"off")
            self.assertFalse(any(svc.view()["gates"].values()))
            stop_service()
            rows=journal.snapshot()["rows"]
            codes=[r["code"] for r in rows]
            self.assertEqual(codes[0],"app_started")
            self.assertEqual(codes.count("mqtt_connected"),1)
            self.assertIn("mqtt_disconnected",codes)
            self.assertIn("night_mode_on",codes)
            self.assertIn("night_mode_off",codes)
            self.assertTrue(any(r["code"]=="gate_ready" and r["params"]["gate"]=="System Ready" for r in rows))
            self.assertTrue(any(r["code"]=="gate_not_ready" and r["params"]["gate"]=="System Ready" for r in rows))
            self.assertIn("operation_success",codes)
            actor.disconnect();actor.loop_stop()

    @staticmethod
    def stop_proc(p):
        if p.poll() is None:
            p.terminate()
            try:p.wait(5)
            except subprocess.TimeoutExpired:p.kill();p.wait()


if __name__=="__main__":
    unittest.main()
