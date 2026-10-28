"""Durable, transient Home Assistant MQTT Event publisher for DH Network App.

The Go collector owns SQLite inventory. This worker only reads first-positive
entries and marks an event published after MQTT QoS 1 PUBACK. The first
inventory after initial install / Reset is suppressed, not replayed as alerts.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

ROOT = "DigitalHouses/Global/dh_network_app"
AVAILABILITY = ROOT + "/availability"
EVENT_TOPIC = ROOT + "/event"
DISCOVERY = "homeassistant"
POLL_INTERVAL_SECONDS = 4
ENRICHMENT_DELAY_SECONDS = 12
DB = Path(os.environ.get("DH_DB", "/data/network.sqlite3"))
LOG = logging.getLogger("dh_network_app.mqtt")

def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

def event_payload(row: sqlite3.Row) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": 2,
        "event_type": "device_discovered",
        "observed_at": row["first_positive_at"],
        "device_id": row["device_id"],
        "detection_source": row["detection_source"],
    }
    if row["mac"]:
        result["mac"] = row["mac"]
    if row["ipv4"]:
        result["ipv4"] = row["ipv4"]
    name = row["display_name"].strip()
    if name and name.casefold() != (row["mac"] or "").casefold():
        result["name"] = name
    return result

def discovery_payloads(version: str, started: str) -> dict[str, dict[str, Any]]:
    device = {
        "identifiers": ["dh_network_app"],
        "name": "DigitalHouses Network App",
        "manufacturer": "DigitalHouses",
        "model": "Network App",
        "sw_version": version,
    }
    origin = {"name": "DigitalHouses Network App", "sw_version": version}
    available = [{"topic": AVAILABILITY, "payload_available": "online", "payload_not_available": "offline"}]
    common = {"device": device, "origin": origin, "availability": available, "qos": 1}
    return {
        "homeassistant/event/dh_network_app_network/config": {
            **common,
            "unique_id": "dh_network_app_network",
            "default_entity_id": "event.dh_network_app_network",
            "name": "Network events",
            "state_topic": EVENT_TOPIC,
            "event_types": ["device_discovered"],
        },
        "homeassistant/sensor/dh_network_app_version/config": {
            **common,
            "unique_id": "dh_network_app_version",
            "default_entity_id": "sensor.dh_network_app_version",
            "name": "Version",
            "entity_category": "diagnostic",
            "state_topic": ROOT + "/version/state",
        },
        "homeassistant/sensor/dh_network_app_started_at/config": {
            **common,
            "unique_id": "dh_network_app_started_at",
            "default_entity_id": "sensor.dh_network_app_started_at",
            "name": "Started at",
            "device_class": "timestamp",
            "entity_category": "diagnostic",
            "state_topic": ROOT + "/started_at/state",
        },
    }

def pending_births(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute("""
        SELECT b.device_id,b.first_positive_at,d.display_name,d.mac,d.ipv4,
          CASE
            WHEN EXISTS(SELECT 1 FROM ipv4_evidence i
                        WHERE i.device_id=b.device_id AND i.source='arp' AND i.state='observed')
              THEN 'arp'
            WHEN EXISTS(SELECT 1 FROM identities i
                        WHERE i.device_id=b.device_id AND i.kind='ha_entity')
              THEN 'ha_device_tracker'
            WHEN EXISTS(SELECT 1 FROM ipv4_evidence i
                        WHERE i.device_id=b.device_id AND i.source='local_interface')
              THEN 'local_interface'
            ELSE 'other_positive'
          END AS detection_source
        FROM device_births b JOIN devices d ON d.id=b.device_id
        WHERE b.publish_state='pending'
        ORDER BY b.first_positive_at,b.device_id LIMIT 32
    """).fetchall()

def suppress_initial_births(conn: sqlite3.Connection, births: list[sqlite3.Row]) -> list[sqlite3.Row]:
    record = conn.execute("SELECT value FROM network_event_policy WHERE key='baseline_until'").fetchone()
    baseline = parse_utc(record[0]) if record else None
    ready = []
    for row in births:
        if baseline is not None and parse_utc(row["first_positive_at"]) <= baseline:
            conn.execute("UPDATE device_births SET publish_state='suppressed' WHERE device_id=? AND publish_state='pending'", (row["device_id"],))
        else:
            ready.append(row)
    conn.commit()
    return ready

class MQTTEvents:
    def __init__(self, host: str, port: int, username: str, password: str, version: str, started: str) -> None:
        if mqtt is None:
            raise RuntimeError("py3-paho-mqtt must be installed")
        self.connected = threading.Event()
        self.version = version
        self.started = started
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="dh-network-events")
        except AttributeError:
            self.client = mqtt.Client(client_id="dh-network-events")
        if username:
            self.client.username_pw_set(username, password)
        self.client.will_set(AVAILABILITY, "offline", qos=1, retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.connect_async(host, port, 60)
        self.client.loop_start()

    def publish_checked(self, topic: str, content: str, retain: bool) -> bool:
        info = self.client.publish(topic, content, qos=1, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            return False
        info.wait_for_publish(timeout=8)
        return info.is_published()

    def publish_discovery(self) -> None:
        for topic, body in discovery_payloads(self.version, self.started).items():
            self.client.publish(topic, json.dumps(body, ensure_ascii=False, separators=(",", ":")), qos=1, retain=True)
        self.client.publish(ROOT+"/version/state", self.version, qos=1, retain=True)
        self.client.publish(ROOT+"/started_at/state", self.started, qos=1, retain=True)
        self.client.publish(AVAILABILITY, "online", qos=1, retain=True)

    def on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, *args: Any) -> None:
        if reason_code != 0:
            self.connected.clear()
            LOG.warning("MQTT rejected connection: %s", reason_code)
            return
        self.connected.set()
        client.subscribe("homeassistant/status", qos=1)
        self.publish_discovery()
        LOG.info("MQTT Discovery registered; event transport QoS=1 retain=false")

    def on_disconnect(self, *args: Any) -> None:
        self.connected.clear()

    def on_message(self, client: Any, userdata: Any, message: Any) -> None:
        if message.topic == "homeassistant/status" and message.payload == b"online":
            self.publish_discovery()

    def send_birth(self, conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
        if not self.connected.is_set():
            return False
        payload = event_payload(row)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if not self.publish_checked(EVENT_TOPIC, body, retain=False):
            return False
        # If Reset removed this UUID while MQTT was in-flight, do not restore it.
        with conn:
            changed = conn.execute(
                "UPDATE device_births SET publish_state='published' WHERE device_id=? AND publish_state='pending'",
                (row["device_id"],)
            ).rowcount
            if changed:
                conn.execute(
                    "INSERT INTO events(event_type,device_id,occurred_at,data_json) VALUES(?,?,?,?)",
                    ("device_discovered", row["device_id"], datetime.now(timezone.utc).isoformat(), body),
                )
        return True

def run_forever() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    host = os.getenv("MQTT_HOST", "")
    if not host:
        LOG.warning("MQTT service not connected; network inventory continues but HA event publishing is unavailable")
        return
    mqtt_events = MQTTEvents(host, int(os.environ["MQTT_PORT"]), os.getenv("MQTT_USER", ""),
                             os.getenv("MQTT_PASSWORD", ""), os.environ["APP_VERSION"],
                             os.environ["DH_STARTED_AT"])
    try:
        while True:
            try:
                if not DB.exists():
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue
                with sqlite3.connect(f"file:{DB}?mode=rw", uri=True, timeout=8) as conn:
                    births = suppress_initial_births(conn, pending_births(conn))
                    for row in births:
                        if not mqtt_events.connected.is_set():
                            break
                        if (datetime.now(timezone.utc) - parse_utc(row["first_positive_at"])).total_seconds() < ENRICHMENT_DELAY_SECONDS:
                            continue
                        if not mqtt_events.send_birth(conn, row):
                            break
            except (sqlite3.Error, OSError, ValueError) as exc:
                LOG.warning("Event outbox unavailable; retrying: %s", exc)
            time.sleep(POLL_INTERVAL_SECONDS)
    finally:
        mqtt_events.client.publish(AVAILABILITY, "offline", qos=1, retain=True)
        mqtt_events.client.loop_stop()
        mqtt_events.client.disconnect()

if __name__ == "__main__":
    run_forever()
