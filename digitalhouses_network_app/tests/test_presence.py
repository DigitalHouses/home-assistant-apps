"""The new subscription engine consumes completed shared scans, never private probes."""
from __future__ import annotations
import json
import sqlite3
import sys
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from threading import Event

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"rootfs"/"app"))
from presence import PresenceRunner

class Transport:
    def __init__(self):
        self.connected=Event()
        self.connected.set()
        self.messages=[]
        self.fail=False
    def publish_checked(self,topic,payload,retain):
        self.messages.append((topic,json.loads(payload),retain))
        return not self.fail

def fixture():
    db=sqlite3.connect(":memory:")
    db.row_factory=sqlite3.Row
    db.executescript("""
       CREATE TABLE sources(kind TEXT,status TEXT,last_success TEXT);
       CREATE TABLE devices(id TEXT,mac TEXT);
       CREATE TABLE lan_positive(device_id TEXT,last_seen TEXT);
       CREATE TABLE ipv4_evidence(ipv4 TEXT,source TEXT,state TEXT,last_seen TEXT);
       CREATE TABLE discovery_settings(id INTEGER,scan_interval_seconds INTEGER,confirm_successes INTEGER,confirm_failures INTEGER);
       INSERT INTO discovery_settings VALUES(1,60,2,3);
       CREATE TABLE presence_subscriptions(kind TEXT,target TEXT,enabled INT,notifications INT);
       CREATE TABLE presence_states(kind TEXT,target TEXT,state TEXT DEFAULT 'unknown',
          last_confirmed TEXT DEFAULT '',last_sample_at TEXT DEFAULT '',
          last_check TEXT DEFAULT '',last_positive TEXT DEFAULT '',
          last_changed TEXT DEFAULT '',successes INT DEFAULT 0,failures INT DEFAULT 0,
          reason TEXT DEFAULT '', PRIMARY KEY(kind,target));
       CREATE TABLE presence_outbox(event_id TEXT PRIMARY KEY,kind TEXT,target TEXT,occurred_at TEXT,payload_json TEXT);
       CREATE TABLE event_delivery_log(event_id TEXT PRIMARY KEY,event_type TEXT,occurred_at TEXT,
          published_at TEXT DEFAULT '',status TEXT,attempts INT DEFAULT 0,payload_json TEXT);
       INSERT INTO sources VALUES('lan_arp','ok',NULL);
       INSERT INTO devices VALUES('device-a','E8:FF:1E:D7:3A:48');
       INSERT INTO presence_subscriptions VALUES('ip','192.168.2.30',1,0);
       INSERT INTO presence_subscriptions VALUES('mac','E8:FF:1E:D7:3A:48',1,1);
    """)
    return db

def scan(db,at,seen):
    stamp=at.isoformat()
    with db:
        db.execute("UPDATE sources SET status='ok',last_success=?",(stamp,))
        if seen:
            db.execute("INSERT INTO lan_positive VALUES('device-a',?) ON CONFLICT DO UPDATE SET last_seen=excluded.last_seen",(stamp,))
            db.execute("DELETE FROM ipv4_evidence")
            db.execute("INSERT INTO ipv4_evidence VALUES('192.168.2.30','arp','observed',?)",(stamp,))
    return stamp

class PresenceTests(unittest.TestCase):
    def test_one_global_scan_is_one_sample_and_no_first_event(self):
        db=fixture();engine=PresenceRunner();tx=Transport()
        t=datetime.now(timezone.utc)-timedelta(seconds=75)
        scan(db,t,True)
        engine.cycle(db,tx)
        engine.cycle(db,tx)
        rows=db.execute("SELECT kind,successes,last_confirmed FROM presence_states ORDER BY kind").fetchall()
        self.assertEqual([(x["kind"],x["successes"],x["last_confirmed"]) for x in rows],
                         [("ip",1,""),("mac",1,"")])
        self.assertFalse(tx.messages)
        scan(db,t+timedelta(seconds=15),True);engine.cycle(db,tx)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM presence_outbox").fetchone()[0],0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM event_delivery_log").fetchone()[0],0)
        self.assertEqual(db.execute("SELECT state FROM presence_states WHERE kind='ip'").fetchone()[0],"reachable")

    def test_confirmed_absence_yields_one_event_per_subscription_and_puback(self):
        db=fixture();engine=PresenceRunner();tx=Transport()
        t=datetime.now(timezone.utc)-timedelta(seconds=100)
        for n in range(2):
            scan(db,t+timedelta(seconds=15*n),True);engine.cycle(db,tx)
        for n in range(3):
            scan(db,t+timedelta(seconds=30+15*n),False);engine.cycle(db,tx)
        self.assertEqual(len(tx.messages),2)
        types={row[1]["event_type"] for row in tx.messages}
        self.assertEqual(types,{"tracked_device_absent","tracked_device_unreachable"})
        self.assertTrue(all(topic=="DigitalHouses/Global/dh_network_app/event" and not retained
                            for topic,_,retained in tx.messages))
        rows=db.execute("SELECT status,attempts,published_at,payload_json FROM event_delivery_log").fetchall()
        self.assertEqual(len(rows),2)
        self.assertTrue(all(row["status"]=="broker_acked" and row["attempts"]==1 and row["published_at"] for row in rows))
        self.assertEqual(db.execute("SELECT COUNT(*) FROM presence_outbox").fetchone()[0],0)
        self.assertEqual({json.loads(row["payload_json"])["notifications_requested"] for row in rows},{False,True})

    def test_failure_of_global_source_never_means_device_absent(self):
        db=fixture();engine=PresenceRunner();tx=Transport()
        now=datetime.now(timezone.utc)
        for n in range(2):
            scan(db,now-timedelta(seconds=30-n*10),True);engine.cycle(db,tx)
        with db:db.execute("UPDATE sources SET status='error'")
        engine.cycle(db,tx)
        rows=db.execute("SELECT state FROM presence_states").fetchall()
        self.assertEqual({row["state"] for row in rows},{"unknown"})
        self.assertEqual(len(tx.messages),0)

    def test_retry_without_duplicate_generation(self):
        db=fixture();engine=PresenceRunner();tx=Transport()
        t=datetime.now(timezone.utc)-timedelta(seconds=100)
        for n in range(2):
            scan(db,t+timedelta(seconds=n*10),True);engine.cycle(db,tx)
        tx.fail=True
        for n in range(3):
            scan(db,t+timedelta(seconds=20+n*10),False);engine.cycle(db,tx)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM presence_outbox").fetchone()[0],2)
        self.assertEqual({x["status"] for x in db.execute("SELECT status FROM event_delivery_log")},{"queued","retrying"})
        tx.fail=False;engine.cycle(db,tx)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM presence_outbox").fetchone()[0],0)
        self.assertEqual({x["status"] for x in db.execute("SELECT status FROM event_delivery_log")},{"broker_acked"})
        self.assertEqual(db.execute("SELECT COUNT(*) FROM event_delivery_log").fetchone()[0],2)

class NotificationPackageContract(unittest.TestCase):
    def test_local_ha_package_is_opt_in_and_filters_notification_requested(self):
        import yaml
        path=Path(__file__).resolve().parents[1]/"examples"/"ha_packages"/"dh_network_notifications.yaml"
        data=yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertIn("input_boolean",data)
        self.assertIn("automation",data)
        spec=data["automation"][0]
        self.assertEqual(spec["triggers"][0]["trigger"],"mqtt")
        self.assertEqual(spec["triggers"][0]["topic"],"DigitalHouses/Global/dh_network_app/event")
        condition=spec["conditions"][0]["value_template"]
        self.assertIn("notifications_requested",condition)
        self.assertIn("device_discovered",condition)
        self.assertIn("persistent_notification.create",spec["actions"][-1]["action"])
        self.assertIn("event_identity",spec["actions"][-1]["data"]["notification_id"])

if __name__=="__main__":
    unittest.main()
