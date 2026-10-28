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
       CREATE TABLE sources(kind TEXT,status TEXT,last_success TEXT,details_json TEXT DEFAULT '{}');
       CREATE TABLE devices(id TEXT,mac TEXT);
       CREATE TABLE lan_positive(device_id TEXT,last_seen TEXT);
       CREATE TABLE ipv4_evidence(ipv4 TEXT,source TEXT,state TEXT,last_seen TEXT);
       CREATE TABLE discovery_settings(id INTEGER,scan_interval_seconds INTEGER,confirm_successes INTEGER,confirm_failures INTEGER);
       INSERT INTO discovery_settings VALUES(1,60,2,3);
       CREATE TABLE presence_subscriptions(kind TEXT,target TEXT,enabled INT,notifications INT,updated_at TEXT,label TEXT NOT NULL DEFAULT '');
       CREATE TABLE presence_states(kind TEXT,target TEXT,state TEXT DEFAULT 'unknown',
          last_confirmed TEXT DEFAULT '',last_sample_at TEXT DEFAULT '',
          last_check TEXT DEFAULT '',last_positive TEXT DEFAULT '',
          last_changed TEXT DEFAULT '',successes INT DEFAULT 0,failures INT DEFAULT 0,
          reason TEXT DEFAULT '', PRIMARY KEY(kind,target));
       CREATE TABLE presence_outbox(event_id TEXT PRIMARY KEY,kind TEXT,target TEXT,occurred_at TEXT,payload_json TEXT);
       CREATE TABLE event_delivery_log(event_id TEXT PRIMARY KEY,event_type TEXT,occurred_at TEXT,
          published_at TEXT DEFAULT '',status TEXT,attempts INT DEFAULT 0,payload_json TEXT);
       INSERT INTO sources(kind,status,last_success) VALUES('lan_arp','ok',NULL);
       INSERT INTO devices VALUES('device-a','E8:FF:1E:D7:3A:48');
       INSERT INTO presence_subscriptions VALUES('ip','192.168.2.30',1,0,'2000-01-01T00:00:00Z','Мой ноутбук');
       INSERT INTO presence_subscriptions VALUES('mac','E8:FF:1E:D7:3A:48',1,1,'2000-01-01T00:00:00Z','');
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

    def test_user_label_is_in_new_event_but_address_and_event_type_are_unchanged(self):
        db=fixture();engine=PresenceRunner();tx=Transport()
        t=datetime.now(timezone.utc)-timedelta(seconds=80)
        scan(db,t,True);engine.cycle(db,tx)
        scan(db,t+timedelta(seconds=15),True);engine.cycle(db,tx)
        scan(db,t+timedelta(seconds=30),False)
        # A non-observed scan must remove prior positive evidence.
        with db:
            db.execute("DELETE FROM ipv4_evidence")
            db.execute("DELETE FROM lan_positive")
        engine.cycle(db,tx)
        scan(db,t+timedelta(seconds=45),False);engine.cycle(db,tx)
        scan(db,t+timedelta(seconds=60),False);engine.cycle(db,tx)
        msg=next(x[1] for x in tx.messages if x[1].get("watch_id")=="ip:192.168.2.30")
        self.assertEqual(msg["label"],"Мой ноутбук")
        self.assertEqual(msg["ip"],"192.168.2.30")
        self.assertEqual(msg["event_type"],"tracked_device_unreachable")
        self.assertEqual(msg["previous"],"reachable")
        self.assertEqual(msg["current"],"unreachable")
        self.assertEqual(msg["check_method"],"discovery_arp")
        self.assertEqual(len([x for x in tx.messages if x[1].get("watch_id")=="ip:192.168.2.30"]),1)

    def test_initial_activation_waits_for_new_scan_before_confirming(self):
        db=fixture();engine=PresenceRunner();tx=Transport()
        now=datetime.now(timezone.utc)
        with db:
            db.execute("UPDATE presence_subscriptions SET updated_at=?",
                       ((now-timedelta(seconds=45)).isoformat(),))
            db.execute("INSERT INTO presence_states(kind,target,state,reason) VALUES('ip','192.168.2.30','working','scan_requested')")
            db.execute("INSERT INTO presence_states(kind,target,state,reason) VALUES('mac','E8:FF:1E:D7:3A:48','working','scan_requested')")
        # Fresh at present, but it is a scan from BEFORE activation.
        scan(db,now-timedelta(seconds=60),True)
        engine.cycle(db,tx)
        self.assertEqual(
            {x['state'] for x in db.execute("SELECT state FROM presence_states")},
            {'working'})
        self.assertEqual(
            {x['last_check'] for x in db.execute("SELECT last_check FROM presence_states")},
            {''})
        # The next shared scan provides one sample, not yet confirmation.
        scan(db,now-timedelta(seconds=30),True)
        engine.cycle(db,tx)
        rows=db.execute("SELECT state,successes,last_check FROM presence_states").fetchall()
        self.assertEqual({x['state'] for x in rows},{'confirming'})
        self.assertEqual({x['successes'] for x in rows},{1})
        self.assertTrue(all(x['last_check'] for x in rows))
        # Re-reading the same scan doesn't count as another confirmation.
        engine.cycle(db,tx)
        self.assertEqual({x['successes'] for x in db.execute("SELECT successes FROM presence_states")},{1})
        scan(db,now-timedelta(seconds=15),True)
        engine.cycle(db,tx)
        self.assertEqual({x['state'] for x in db.execute("SELECT state FROM presence_states")},
                         {'reachable','present'})
        self.assertEqual(len(tx.messages),0)  # initial baseline is quiet

    def test_scan_already_running_at_activation_does_not_initialize_presence(self):
        db=fixture();engine=PresenceRunner();tx=Transport()
        now=datetime.now(timezone.utc)
        activation=now-timedelta(seconds=8)
        started=activation-timedelta(seconds=3)
        finished=activation+timedelta(seconds=2)
        with db:
            db.execute("UPDATE presence_subscriptions SET updated_at=?",
                       (activation.isoformat(),))
            db.execute("INSERT INTO presence_states(kind,target,state,reason) VALUES('ip','192.168.2.30','working','scan_requested')")
            db.execute("INSERT INTO presence_states(kind,target,state,reason) VALUES('mac','E8:FF:1E:D7:3A:48','working','scan_requested')")
        scan(db,finished,True)
        with db:
            db.execute("UPDATE sources SET details_json=?",
                       (json.dumps({'scan_started_at':started.isoformat()}),))
        engine.cycle(db,tx)
        self.assertEqual({x['state'] for x in db.execute("SELECT state FROM presence_states")},
                         {'working'})
        # A dedicated scan starts after activation, even if completed very quickly.
        with db:
            db.execute("UPDATE sources SET details_json=?",
                       (json.dumps({'scan_started_at':(activation+timedelta(milliseconds=3)).isoformat()}),))
        scan(db,finished+timedelta(seconds=1),True)
        engine.cycle(db,tx)
        self.assertEqual({x['state'] for x in db.execute("SELECT state FROM presence_states")},
                         {'confirming'})
        self.assertEqual({x['successes'] for x in db.execute("SELECT successes FROM presence_states")},{1})

    def test_failed_new_scan_leaves_clear_unknown_without_fake_absence(self):
        db=fixture();engine=PresenceRunner();tx=Transport()
        now=datetime.now(timezone.utc)
        with db:
            db.execute("UPDATE presence_subscriptions SET updated_at=?",
                       ((now-timedelta(seconds=45)).isoformat(),))
            db.execute("INSERT INTO presence_states(kind,target,state,reason) VALUES('ip','192.168.2.30','working','scan_requested')")
            db.execute("INSERT INTO presence_states(kind,target,state,reason) VALUES('mac','E8:FF:1E:D7:3A:48','working','scan_requested')")
            db.execute("UPDATE sources SET status='error',last_success=NULL,details_json=?",
                       (json.dumps({'observed_at':(now-timedelta(seconds=15)).isoformat()}),))
        engine.cycle(db,tx)
        states=db.execute("SELECT state,reason FROM presence_states").fetchall()
        self.assertEqual({x['state'] for x in states},{'unknown'})
        self.assertEqual({x['reason'] for x in states},{'source_unavailable'})
        self.assertFalse(tx.messages)

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
