"""Regressions for explicit watch configuration and transition-machine semantics."""
from __future__ import annotations
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from pathlib import Path
from threading import Event

ROOT = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(ROOT))
import monitoring as mod


class FakePublisher:
    def __init__(self):
        self.connected = Event()
        self.connected.set()
        self.version = "0.1.19"
        self.connection_epoch = 1
        self.messages = []
    def publish_checked(self, topic, data, retain):
        self.messages.append((topic, data, retain))
        return True


def database():
    c=sqlite3.connect(":memory:")
    c.row_factory=sqlite3.Row
    c.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE monitor_states (method TEXT,watch_id TEXT,state TEXT,last_confirmed TEXT,
          ok_count INT,bad_count INT,last_sample TEXT,last_check TEXT,reason TEXT,target_json TEXT,
          label TEXT,PRIMARY KEY(method,watch_id));
        CREATE TABLE monitor_outbox(event_id TEXT PRIMARY KEY,method TEXT,watch_id TEXT,
          occurred_at TEXT,payload_json TEXT,
          FOREIGN KEY(method,watch_id) REFERENCES monitor_states(method,watch_id));
        CREATE TABLE monitor_tombstones(method TEXT,watch_id TEXT,PRIMARY KEY(method,watch_id));
        CREATE TABLE events(id INTEGER PRIMARY KEY,event_type TEXT,device_id TEXT,occurred_at TEXT,data_json TEXT);
        CREATE TABLE event_delivery_log(event_id TEXT PRIMARY KEY,event_type TEXT,occurred_at TEXT,published_at TEXT DEFAULT '',status TEXT,attempts INTEGER DEFAULT 0,payload_json TEXT);
        CREATE TABLE sources(id TEXT PRIMARY KEY,status TEXT,last_success TEXT);
        CREATE TABLE identities(device_id TEXT,kind TEXT,value TEXT);
        CREATE TABLE lan_positive(device_id TEXT,last_seen TEXT);
        CREATE TABLE ipv4_evidence(device_id TEXT,source TEXT,state TEXT,last_seen TEXT);
    """)
    return c


class TestGroupedYAML(unittest.TestCase):
    def test_all_methods_and_utf8_labels(self):
        watches=mod.parse_config("""
monitored_devices:
  icmp:
    media_server:
      ip: 192.168.11.238
      label: "Медиасервер"
    web_server: 192.168.11.240
  arp:
    workstation: "18:31:BF:2F:ED:37"
  ha_device_tracker:
    phone:
      entity_id: device_tracker.phone
      label: "Телефон"
  tcp:
    plex:
      ip: 192.168.11.238
      port: 32400
      label: "Plex"
""")
        self.assertEqual(len(watches),5)
        self.assertEqual(watches[0].label,"Медиасервер")
        self.assertEqual(watches[1].target,"192.168.11.240")
        self.assertEqual(watches[2].target,"18:31:BF:2F:ED:37")
        self.assertEqual(watches[3].target,"device_tracker.phone")
        self.assertEqual(watches[4].port,32400)
        self.assertEqual(mod.parse_config("monitored_devices: {}\n"),[])
    def test_no_config_creates_no_watch(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(mod.load_config(Path(root)/"not-present.yaml"),[])
    def test_duplicate_methods_ids_targets_and_bad_shapes_rejected(self):
        bad=[
            "monitored_devices: {icmp: {a: 192.168.11.1, a: 192.168.11.2}}",
            "monitored_devices: {unknown: {a: 192.168.11.1}}",
            "monitored_devices: {icmp: [192.168.11.1]}",
            "monitored_devices: {icmp: {a: {ip: 192.168.11.1, extra: value}}}",
            "monitored_devices: {icmp: {a: no-ip}}",
            "monitored_devices: {icmp: {'Bad Name': 192.168.11.1}}",
            "monitored_devices: {icmp: {a: 'ff02::1'}}",
            "monitored_devices: {arp: {a: 'FF:FF:FF:FF:FF:FF'}}",
            "monitored_devices: {ha_device_tracker: {a: sensor.someone}}",
            "monitored_devices: {tcp: {plex: {ip: 192.168.11.238}}}",
            "monitored_devices: {tcp: {plex: {ip: 192.168.11.238, port: 0}}}",
            "monitored_devices: {tcp: {plex: 192.168.11.238}}",
            "monitored_devices: {icmp: {a: {ip: 192.168.11.1, label: ''}}}",
            "monitored_devices: {arp: {a: null}}",
        ]
        for content in bad:
            with self.subTest(content=content),self.assertRaises(mod.ConfigError):
                mod.parse_config(content)


class TestTransitions(unittest.TestCase):
    def setUp(self):
        self.conn=database()
        self.watches=mod.parse_config("""
monitored_devices:
  icmp:
    media_server: 192.168.11.238
  tcp:
    media_server:
      ip: 192.168.11.238
      port: 32400
      label: "Плекс"
""")
        self.runner=mod.MonitorRunner(Path("/nonexistent"))
        self.runner.watches=self.watches
        self.runner.sync(self.conn)
        self.watch=self.watches[0]
        self.time="2026-10-28T08:00:00+00:00"
    def emit(self,outcome,reason="test"):
        self.runner.observe(self.conn,self.watch,outcome,reason,self.time,self.time)
    def state(self,method="icmp"):
        return self.conn.execute("SELECT * FROM monitor_states WHERE method=? AND watch_id='media_server'",(method,)).fetchone()
    def outbox(self):
        return self.conn.execute("SELECT payload_json FROM monitor_outbox ORDER BY occurred_at").fetchall()
    def test_two_success_three_fail_and_no_startup_event(self):
        self.emit("positive")
        self.assertEqual(self.state()["state"],"unknown")
        self.assertEqual(len(self.outbox()),0)
        self.emit("positive")
        self.assertEqual(self.state()["state"],"reachable")
        self.assertEqual(len(self.outbox()),0)
        self.emit("negative")
        self.emit("negative")
        self.assertEqual(self.state()["state"],"reachable")
        self.assertEqual(len(self.outbox()),0)
        self.emit("negative")
        self.assertEqual(self.state()["state"],"unreachable")
        self.assertEqual(len(self.outbox()),1)
        payload=json.loads(self.outbox()[0][0])
        self.assertEqual(payload["event_type"],"tracked_device_unreachable")
        self.assertEqual((payload["previous"],payload["current"]),("reachable","unreachable"))
        self.assertEqual((payload["consecutive_successes"],payload["consecutive_failures"]),(0,3))
        self.assertNotIn("label",payload)
        self.emit("negative")
        self.assertEqual(len(self.outbox()),1)
        self.emit("positive")
        self.emit("positive")
        self.assertEqual(self.state()["state"],"reachable")
        self.assertEqual(len(self.outbox()),2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],2)
    def test_unknown_preserves_prior_confirmed_without_false_absent(self):
        self.emit("positive")
        self.emit("positive")
        self.emit("unknown","source_unavailable")
        self.assertEqual(self.state()["state"],"unknown")
        self.assertEqual(self.state()["last_confirmed"],"reachable")
        self.assertEqual(len(self.outbox()),0)
        self.emit("positive")
        self.emit("positive")
        self.assertEqual(len(self.outbox()),0)
    def test_multi_method_is_independent(self):
        self.emit("positive")
        self.emit("positive")
        self.assertEqual(self.state()["state"],"reachable")
        self.assertEqual(self.state("tcp")["state"],"unknown")
    def test_label_changes_do_not_change_identity(self):
        self.emit("positive")
        self.emit("positive")
        w=self.watches[0]
        self.runner.watches=[mod.Watch(w.method,w.watch_id,w.target,label="Новая подпись"),self.watches[1]]
        self.runner.sync(self.conn)
        self.assertEqual(self.state()["state"],"reachable")
        self.assertEqual(self.state()["label"],"Новая подпись")
    def test_mqtt_retained_before_transient_and_restart(self):
        self.emit("positive");self.emit("positive")
        self.emit("negative");self.emit("negative");self.emit("negative")
        fake=FakePublisher()
        self.runner.publish(self.conn,fake)
        topics=[i[0] for i in fake.messages]
        self.assertEqual(topics[-1],mod.ROOT+"/event")
        self.assertFalse(fake.messages[-1][2])
        self.assertIn(self.watch.state_topic(),topics)
        self.assertEqual(len(self.outbox()),0)
        before=len(fake.messages)
        self.runner.publish(self.conn,fake)
        self.assertEqual(len(fake.messages),before)
        restarted=mod.MonitorRunner(Path("/not-real"))
        restarted.watches=self.watches
        restarted.sync(self.conn)
        self.assertEqual(self.state()["state"],"unreachable")
        restarted.publish(self.conn,fake)
        self.assertGreater(len(fake.messages),before)
    def test_removed_watch_deletes_discovery_without_orphan_event(self):
        self.emit("positive");self.emit("positive")
        self.emit("negative");self.emit("negative");self.emit("negative")
        self.runner.watches=[self.watches[1]]
        self.runner.sync(self.conn)
        self.assertEqual(len(self.outbox()),0)
        fake=FakePublisher()
        self.runner.publish(self.conn,fake)
        self.assertIn((self.watch.discovery_topic(),"",True),fake.messages)


class TestARP(unittest.TestCase):
    def test_no_stale_duplicate_and_missing_not_a_physical_offline_proof(self):
        conn=database()
        watch=mod.Watch("arp","laptop","18:31:BF:2F:ED:37")
        self.assertEqual(mod.arp_probe(conn,watch,"")[0],"unknown")
        conn.execute("INSERT INTO sources VALUES ('LAN ARP','ok','2026-10-28T08:00:00Z')")
        conn.execute("INSERT INTO identities VALUES('uuid1','mac',?)",(watch.target,))
        # local_interface positive evidence alone cannot prove an ARP reply.
        conn.execute("INSERT INTO lan_positive VALUES ('uuid1','2026-10-28T08:00:00Z')")
        self.assertEqual(mod.arp_probe(conn,watch,"")[0],"negative")
        conn.execute("INSERT INTO ipv4_evidence VALUES ('uuid1','arp','observed','2026-10-28T08:00:00Z')")
        result,reason,sample=mod.arp_probe(conn,watch,"")
        self.assertEqual((result,reason),("positive","arp_positive"))
        self.assertEqual(mod.arp_probe(conn,watch,sample)[0],"skip")
        conn.execute("UPDATE sources SET last_success='2026-10-28T08:03:00Z'")
        result,reason,_=mod.arp_probe(conn,watch,sample)
        self.assertEqual((result,reason),("negative","arp_not_observed"))



class TestHAReportFreshness(unittest.TestCase):
    class MockResponse:
        def __init__(self, entity_id, state, timestamp):
            self.body = json.dumps({"entity_id":entity_id,"state":state,"last_reported":timestamp}).encode()
            self.status = 200
        def __enter__(self):
            return self
        def __exit__(self,*args):
            return None
        def read(self,*args):
            return self.body

    def test_same_rest_snapshot_never_counts_twice(self):
        conn=database()
        runner=mod.MonitorRunner(Path("/not-real"))
        watch=mod.Watch("ha_device_tracker","phone","device_tracker.phone",label="Телефон")
        runner.watches=[watch]
        runner.sync(conn)
        reported=datetime.now(timezone.utc).isoformat()
        response=self.MockResponse(watch.target,"home",reported)
        with patch.dict("os.environ",{"SUPERVISOR_TOKEN":"test-token"}),patch.object(mod.urllib.request,"urlopen",return_value=response):
            first=runner.sample(conn,watch,"")
            self.assertEqual(first[:2],("positive","tracker_home"))
            runner.observe(conn,watch,*first,datetime.now(timezone.utc).isoformat())
            second=runner.sample(conn,watch,first[2])
            self.assertEqual(second[0],"skip")
            runner.observe(conn,watch,*second,datetime.now(timezone.utc).isoformat())
            state=conn.execute("SELECT state,ok_count FROM monitor_states").fetchone()
            self.assertEqual((state["state"],state["ok_count"]),("unknown",1))
            new_report=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()
            response.body=self.MockResponse(watch.target,"home",new_report).body
            third=runner.sample(conn,watch,first[2])
            self.assertEqual(third[0],"positive")
            runner.observe(conn,watch,*third,datetime.now(timezone.utc).isoformat())
        state=conn.execute("SELECT state,last_confirmed FROM monitor_states").fetchone()
        self.assertEqual((state["state"],state["last_confirmed"]),("present","present"))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM monitor_outbox").fetchone()[0],0)
        conn.close()

    def test_tracker_stale_or_missing_report_is_unknown(self):
        entity="device_tracker.phone"
        stale=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
        for report,expected in [(stale,"tracker_stale_report"),
                                ("","tracker_report_timestamp_missing"),
                                ("not-a-date","tracker_report_timestamp_invalid")]:
            response=self.MockResponse(entity,"not_home",report)
            with self.subTest(report=report),patch.dict("os.environ",{"SUPERVISOR_TOKEN":"test-token"}),patch.object(mod.urllib.request,"urlopen",return_value=response):
                self.assertEqual(mod.tracker_probe(entity)[:2],("unknown",expected))
        # Unsupported state remains unknown, even with a fresh timestamp.
        response=self.MockResponse(entity,"unavailable",datetime.now(timezone.utc).isoformat())
        with patch.dict("os.environ",{"SUPERVISOR_TOKEN":"test-token"}),patch.object(mod.urllib.request,"urlopen",return_value=response):
            self.assertEqual(mod.tracker_probe(entity)[0],"unknown")

    def test_three_independent_not_home_reports_are_required(self):
        conn=database()
        runner=mod.MonitorRunner(Path("/not-real"))
        watch=mod.Watch("ha_device_tracker","phone","device_tracker.phone")
        runner.watches=[watch]
        runner.sync(conn)
        response=self.MockResponse(watch.target,"not_home",datetime.now(timezone.utc).isoformat())
        with patch.dict("os.environ",{"SUPERVISOR_TOKEN":"test-token"}),patch.object(mod.urllib.request,"urlopen",return_value=response):
            last=""
            for i in range(3):
                response.body=self.MockResponse(watch.target,"not_home",
                         (datetime.now(timezone.utc)+timedelta(seconds=i)).isoformat()).body
                outcome,reason,sample=runner.sample(conn,watch,last)
                self.assertEqual(outcome,"negative")
                runner.observe(conn,watch,outcome,reason,sample,sample)
                last=sample
                state=conn.execute("SELECT state FROM monitor_states").fetchone()[0]
                self.assertEqual(state,"absent" if i==2 else "unknown")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM monitor_outbox").fetchone()[0],0)
        conn.close()


class TestMQTTReconnect(unittest.TestCase):
    def test_very_short_disconnect_reconnect_republishes_all_retained(self):
        conn=database()
        runner=mod.MonitorRunner(Path("/not-real"))
        runner.watches=[mod.Watch("icmp","node","192.168.11.30")]
        runner.sync(conn)
        fake=FakePublisher()
        runner.publish(conn,fake)
        initial=len(fake.messages)
        self.assertGreater(initial,0)
        runner.publish(conn,fake)
        self.assertEqual(len(fake.messages),initial)
        # Connected before and after: the worker never observed offline.
        fake.connection_epoch += 1
        runner.publish(conn,fake)
        self.assertEqual(len(fake.messages),initial*2)
        conn.close()



if __name__=="__main__":
    unittest.main()
