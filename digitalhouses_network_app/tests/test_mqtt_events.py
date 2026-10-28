"""Contract and SQLite outbox regression checks: no MQTT broker needed."""
from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "rootfs/app/mqtt_events.py"
SPEC = importlib.util.spec_from_file_location("dh_network_mqtt_events", ROOT)
assert SPEC and SPEC.loader
events = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(events)

class TestMQTTEventContract(unittest.TestCase):
    def test_machine_payload_has_no_localized_presentation(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE sample (device_id TEXT, first_positive_at TEXT, display_name TEXT, mac TEXT, ipv4 TEXT, detection_source TEXT)")
        conn.execute("INSERT INTO sample VALUES (?,?,?,?,?,?)",(
            "uuid-1","2026-10-28T08:00:00+05:00","VIEW71","18:31:BF:2F:ED:37","192.168.11.71","arp"))
        event = events.event_payload(conn.execute("SELECT * FROM sample").fetchone())
        self.assertEqual(event["schema_version"], 2)
        self.assertEqual(event["event_type"], "device_discovered")
        self.assertEqual(event["detection_source"], "arp")
        self.assertEqual(event["device_id"], "uuid-1")
        self.assertEqual(event["ipv4"], "192.168.11.71")
        self.assertEqual(event["name"], "VIEW71")
        for field in ("title","message","notification","telegram","severity","emoji"):
            self.assertNotIn(field, event)

    def test_retries_keep_the_same_event_id(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE sample (device_id TEXT, first_positive_at TEXT, display_name TEXT, mac TEXT, ipv4 TEXT, detection_source TEXT)")
        conn.execute("INSERT INTO sample VALUES ('device-1','2026-10-28T08:00:00+05:00','VIEW71','','','arp')")
        row = conn.execute("SELECT * FROM sample").fetchone()
        first = events.event_payload(row)
        self.assertEqual(first["event_id"], events.event_payload(row)["event_id"])
        self.assertEqual(first["detection_source"], "arp")
        self.assertNotIn("mac", first)
        self.assertNotIn("ipv4", first)

    def test_incomplete_census_never_emits_pending_births(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
          CREATE TABLE network_event_policy (key TEXT PRIMARY KEY,value TEXT);
          CREATE TABLE device_births (device_id TEXT PRIMARY KEY,publish_state TEXT);
          INSERT INTO network_event_policy VALUES ('baseline_active','1');
          INSERT INTO device_births VALUES ('uuid-census','pending');
        """)
        birth = {"device_id":"uuid-census","first_positive_at":"2026-10-28T08:00:00+05:00"}
        self.assertEqual(events.suppress_initial_births(conn,[birth]),[])
        self.assertEqual(conn.execute("SELECT publish_state FROM device_births").fetchone()[0],"pending")
        conn.execute("UPDATE network_event_policy SET value='0'")
        self.assertEqual(events.suppress_initial_births(conn,[birth]),[birth])

    def test_mac_like_device_name_does_not_become_guessed_name(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE sample (device_id TEXT, first_positive_at TEXT, display_name TEXT, mac TEXT, ipv4 TEXT, detection_source TEXT)")
        conn.execute("INSERT INTO sample VALUES (?,?,?,?,?,?)",(
            "uuid-1","2026-10-28T08:00:00+05:00","18:31:BF:2F:ED:37","18:31:BF:2F:ED:37","","arp"))
        payload = events.event_payload(conn.execute("SELECT * FROM sample").fetchone())
        self.assertNotIn("name", payload)
        self.assertNotIn("ipv4", payload)

    def test_event_discovery_only_accepts_machine_event_type(self):
        config = events.discovery_payloads("0.1.16", "2026-10-28T08:00:00Z")
        event = config["homeassistant/event/dh_network_app_network/config"]
        self.assertEqual(event["event_types"], ["device_discovered"])
        self.assertEqual(event["state_topic"], events.EVENT_TOPIC)
        self.assertEqual(event["qos"], 1)
        self.assertEqual(event["default_entity_id"], "event.dh_network_app_network")
        self.assertEqual(event["device"]["sw_version"], "0.1.16")

    def test_initial_census_suppressed_but_later_event_remains_pending(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
          CREATE TABLE network_event_policy (key TEXT PRIMARY KEY,value TEXT);
          CREATE TABLE device_births (device_id TEXT PRIMARY KEY,publish_state TEXT);
        """)
        threshold = datetime.now(timezone.utc)
        before = (threshold-timedelta(minutes=1)).isoformat()
        after = (threshold+timedelta(minutes=1)).isoformat()
        conn.execute("INSERT INTO network_event_policy VALUES('baseline_until',?)",(threshold.isoformat(),))
        conn.executemany("INSERT INTO device_births VALUES(?, 'pending')",[("old",),("new",)])
        births = [{"device_id":"old","first_positive_at":before},
                  {"device_id":"new","first_positive_at":after}]
        keep = events.suppress_initial_births(conn,births)
        self.assertEqual([x["device_id"] for x in keep], ["new"])
        self.assertEqual(conn.execute("SELECT publish_state FROM device_births WHERE device_id='old'").fetchone()[0],"suppressed")
        self.assertEqual(conn.execute("SELECT publish_state FROM device_births WHERE device_id='new'").fetchone()[0],"pending")

if __name__ == "__main__":
    unittest.main()
