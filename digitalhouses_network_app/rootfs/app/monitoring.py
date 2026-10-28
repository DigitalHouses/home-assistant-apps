"""Explicit, read-only device monitoring, independent of inventory Online status.

Configuration: /data/monitored_devices.yaml, managed atomically via Ingress.
No watched device is configured by default. Sources remain independently scoped.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import socket
import sqlite3
import struct
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import yaml

LOG = logging.getLogger("dh_network_app.monitoring")
CONFIG = Path(os.getenv("DH_MONITORED_CONFIG", "/data/monitored_devices.yaml"))
METHODS = ("icmp", "arp", "ha_device_tracker", "tcp")
ID = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
ENTITY = re.compile(r"device_tracker\.[a-z0-9_]+\Z")
MAC = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\Z")
ROOT = "DigitalHouses/Global/dh_network_app"
SUCCESSES = 2
FAILURES = 3
CHECK_SECONDS = {"icmp": 30, "tcp": 30, "arp": 30, "ha_device_tracker": 60}


class ConfigError(ValueError):
    pass


class StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        result = {}
        for key_node, val_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ConfigError(f"YAML mapping key must be a string, line {key_node.start_mark.line+1}")
            if key in result:
                raise ConfigError(f"duplicate YAML key {key!r}, line {key_node.start_mark.line+1}")
            result[key] = self.construct_object(val_node, deep=deep)
        return result


@dataclass(frozen=True)
class Watch:
    method: str
    watch_id: str
    target: str
    port: int | None = None
    label: str | None = None

    def key(self) -> tuple[str, str]:
        return self.method, self.watch_id

    def target_json(self) -> str:
        return json.dumps({"target": self.target, "port": self.port}, sort_keys=True)

    def state_topic(self) -> str:
        return f"{ROOT}/monitor/{self.method}/{self.watch_id}/state"

    def attrs_topic(self) -> str:
        return f"{ROOT}/monitor/{self.method}/{self.watch_id}/attributes"

    def discovery_topic(self) -> str:
        return f"homeassistant/sensor/dh_network_monitor_{self.method}_{self.watch_id}/config"


def parse_config(content: str) -> list[Watch]:
    try:
        document = yaml.load(content, Loader=StrictLoader)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid monitored_devices YAML: {exc}") from exc
    if not isinstance(document, dict) or set(document) != {"monitored_devices"}:
        raise ConfigError("root must contain only monitored_devices: { ... }")
    groups = document["monitored_devices"]
    if not isinstance(groups, dict):
        raise ConfigError("monitored_devices must be a mapping by method")
    unknown = set(groups) - set(METHODS)
    if unknown:
        raise ConfigError(f"monitored_devices: unknown methods {sorted(unknown)}")
    watches: list[Watch] = []
    for method in METHODS:
        group = groups.get(method, {})
        if not isinstance(group, dict):
            raise ConfigError(f"monitored_devices.{method} must be a mapping")
        for watch_id, definition in group.items():
            path = f"monitored_devices.{method}.{watch_id}"
            if not isinstance(watch_id, str) or not ID.fullmatch(watch_id):
                raise ConfigError(f"{path}: watch_id must match [a-z][a-z0-9_]{{0,63}}")
            required = {"icmp": "ip", "arp": "mac", "ha_device_tracker": "entity_id", "tcp": "ip"}[method]
            if isinstance(definition, str) and method != "tcp":
                definition = {required: definition}
            if not isinstance(definition, dict):
                raise ConfigError(f"{path}: expected a target mapping" +
                                  (" or scalar" if method != "tcp" else " with ip and port"))
            keys = {required, "label"} | ({"port"} if method == "tcp" else set())
            if set(definition) - keys:
                raise ConfigError(f"{path}: unknown keys {sorted(set(definition)-keys)}")
            target = definition.get(required)
            if not isinstance(target, str) or not target.strip():
                raise ConfigError(f"{path}.{required}: nonempty string required")
            target = target.strip()
            if method in ("icmp", "tcp"):
                try:
                    target = str(ipaddress.ip_address(target))
                except ValueError as exc:
                    raise ConfigError(f"{path}.ip: valid numeric IP required") from exc
                if ipaddress.ip_address(target).is_unspecified or ipaddress.ip_address(target).is_multicast:
                    raise ConfigError(f"{path}.ip: unspecified/multicast address rejected")
                if method == "icmp" and ipaddress.ip_address(target).version != 4:
                    raise ConfigError(f"{path}.ip: ICMPv4 only (IPv6 ICMP is not implemented)")
            if method == "arp":
                if not MAC.fullmatch(target):
                    raise ConfigError(f"{path}.mac: six octets in colon format required")
                first_octet = int(target[:2], 16)
                if first_octet & 1 or int(target.replace(":", ""), 16) == 0:
                    raise ConfigError(f"{path}.mac: multicast/zero MAC rejected")
                target = target.upper()
            if method == "ha_device_tracker" and not ENTITY.fullmatch(target):
                raise ConfigError(f"{path}.entity_id: device_tracker.<object_id> required")
            port = None
            if method == "tcp":
                value = definition.get("port")
                if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
                    raise ConfigError(f"{path}.port: integer 1..65535 required")
                port = value
            label = definition.get("label")
            if label is not None and (not isinstance(label, str) or
                                     not label.strip() or len(label) > 120):
                raise ConfigError(f"{path}.label: nonempty UTF-8 string up to 120 characters required")
            watches.append(Watch(method, watch_id, target, port, label))
    return watches


def load_config(path: Path = CONFIG) -> list[Watch]:
    if not path.exists():
        return []
    return parse_config(path.read_text(encoding="utf-8"))


def _checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\0"
    total = sum(struct.unpack(f"!{len(data)//2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def icmp_probe(ip: str) -> tuple[str, str]:
    """Raw ICMPv4 Echo Request, no shell, ping executable or Nmap."""
    ident = os.getpid() & 0xFFFF
    seq = int(time.monotonic_ns() & 0xFFFF)
    payload = struct.pack("!BBHHH", 8, 0, 0, ident, seq) + b"DH-NETWORK"
    packet = struct.pack("!BBHHH", 8, 0, _checksum(payload), ident, seq) + b"DH-NETWORK"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP) as sock:
            sock.settimeout(1.5)
            sock.sendto(packet, (ip, 0))
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                try:
                    packet, addr = sock.recvfrom(2048)
                except socket.timeout:
                    break
                if addr[0] != ip or len(packet) < 28:
                    continue
                length = (packet[0] & 0x0F) * 4
                if len(packet) < length + 8:
                    continue
                kind, _, _, recv_id, recv_seq = struct.unpack("!BBHHH", packet[length:length+8])
                if kind == 0 and recv_id == ident and recv_seq == seq:
                    return "positive", "icmp_echo_reply"
        return "negative", "icmp_timeout"
    except (PermissionError, OSError) as exc:
        if isinstance(exc, PermissionError) or getattr(exc, "errno", None) in (1, 13):
            return "unknown", "icmp_raw_socket_unavailable"
        return "unknown", "icmp_socket_error"


def tcp_probe(ip: str, port: int) -> tuple[str, str]:
    try:
        with socket.create_connection((ip, port), timeout=1.5):
            return "positive", "tcp_connected"
    except (TimeoutError, ConnectionRefusedError, OSError):
        return "negative", "tcp_connection_failed"


def tracker_probe(entity_id: str) -> tuple[str, str, str]:
    """Only a NEW HA last_reported revision is an independent observation.

    REST GETs of an unchanged cached state cannot accumulate debounce counts.
    An entity which has stopped reporting becomes unknown, never absent.
    """
    token = os.getenv("SUPERVISOR_TOKEN", "")
    if not token:
        return "unknown", "ha_token_missing", ""
    request = urllib.request.Request(
        "http://supervisor/core/api/states/" + entity_id,
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status != 200:
                return "unknown", "ha_source_unavailable", ""
            body = json.load(response)
        if not isinstance(body, dict) or body.get("entity_id") != entity_id:
            return "unknown", "ha_invalid_entity", ""
        value = body.get("state")
        if value not in ("home", "not_home"):
            return "unknown", "tracker_unavailable", ""
        reported = body.get("last_reported")
        if not isinstance(reported, str) or not reported:
            return "unknown", "tracker_report_timestamp_missing", ""
        try:
            timestamp = datetime.fromisoformat(reported.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                return "unknown", "tracker_report_timestamp_invalid", ""
            age = (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()
            if age < -5 or age > 180:
                return "unknown", "tracker_stale_report", ""
        except ValueError:
            return "unknown", "tracker_report_timestamp_invalid", ""
        return ("positive" if value == "home" else "negative",
                "tracker_home" if value == "home" else "tracker_not_home",
                timestamp.astimezone(timezone.utc).isoformat())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return "unknown", "ha_source_unavailable", ""


def arp_probe(conn: sqlite3.Connection, watch: Watch, last_sample: str) -> tuple[str, str, str]:
    source = conn.execute("SELECT status,last_success FROM sources WHERE id='LAN ARP'").fetchone()
    if not source or source["status"] not in ("ok", "degraded", "empty") or not source["last_success"]:
        return "unknown", "arp_source_unavailable", last_sample
    scan = source["last_success"]
    if scan == last_sample:
        return "skip", "arp_no_fresh_snapshot", last_sample
    # Only a direct ARP observation can prove this ARP check. In particular,
    # lan_positive includes local_interface and must not be treated as ARP.
    seen = conn.execute("""
       SELECT e.last_seen FROM identities i JOIN ipv4_evidence e
         ON e.device_id=i.device_id AND e.source='arp' AND e.state='observed'
       WHERE i.kind='mac' AND i.value=? ORDER BY e.last_seen DESC LIMIT 1
    """, (watch.target,)).fetchone()
    if seen:
        try:
            age = (datetime.fromisoformat(scan.replace("Z", "+00:00")) -
                   datetime.fromisoformat(seen["last_seen"].replace("Z", "+00:00"))).total_seconds()
            if 0 <= age < 2:
                return "positive", "arp_positive", scan
        except ValueError:
            return "unknown", "arp_invalid_timestamp", last_sample
    return "negative", "arp_not_observed", scan


def state_value(method: str, success: bool) -> str:
    if method in ("icmp", "tcp"):
        return "reachable" if success else "unreachable"
    return "present" if success else "absent"


def discovery_payload(watch: Watch, version: str) -> dict[str, Any]:
    return {
        "device": {"identifiers": ["dh_network_app"], "name": "DigitalHouses Network App",
                   "manufacturer": "DigitalHouses", "model": "Network App",
                   "sw_version": version},
        "origin": {"name": "DigitalHouses Network App", "sw_version": version},
        "availability": [{"topic": ROOT+"/availability", "payload_available": "online",
                          "payload_not_available": "offline"}],
        "qos": 1,
        "unique_id": f"dh_network_monitor_{watch.method}_{watch.watch_id}",
        "default_entity_id": f"sensor.dh_network_monitor_{watch.method}_{watch.watch_id}",
        "name": watch.label or watch.watch_id,
        "state_topic": watch.state_topic(),
        "json_attributes_topic": watch.attrs_topic(),
        "entity_category": "diagnostic",
    }


class MonitorRunner:
    def __init__(self, path: Path = CONFIG) -> None:
        self.path = path
        self.watches: list[Watch] = []
        self.config_stamp: tuple[int, int] | None = None
        self.next_due: dict[tuple[str, str], float] = {}
        self.force_publish = True
        self.last_connect = False
        self.last_connection_epoch: int | None = None
        self.published: dict[str, str] = {}

    def retained(self, mqtt_events: Any, topic: str, content: str) -> bool:
        if self.published.get(topic) == content:
            return True
        if not mqtt_events.publish_checked(topic, content, True):
            return False
        self.published[topic] = content
        return True

    def reload(self) -> None:
        try:
            stat = self.path.stat() if self.path.exists() else None
            stamp = (stat.st_mtime_ns, stat.st_size) if stat else (0, 0)
            if stamp == self.config_stamp:
                return
            updated = load_config(self.path)
            self.watches = updated
            self.config_stamp = stamp
            self.force_publish = True
            self.next_due = {}
            LOG.info("Monitoring YAML loaded: %d configured checks", len(updated))
        except (ConfigError, OSError, UnicodeError) as exc:
            LOG.error("Keeping last validated monitored_devices YAML: %s", exc)

    def sync(self, conn: sqlite3.Connection) -> None:
        defined = {w.key(): w for w in self.watches}
        with conn:
            for row in conn.execute("SELECT method,watch_id FROM monitor_states").fetchall():
                key = (row["method"], row["watch_id"])
                if key not in defined:
                    conn.execute("INSERT OR IGNORE INTO monitor_tombstones(method,watch_id) VALUES(?,?)",key)
                    conn.execute("DELETE FROM monitor_outbox WHERE method=? AND watch_id=?",key)
                    conn.execute("DELETE FROM monitor_states WHERE method=? AND watch_id=?",key)
            for watch in self.watches:
                spec = watch.target_json()
                old = conn.execute("SELECT target_json FROM monitor_states WHERE method=? AND watch_id=?",watch.key()).fetchone()
                if old is None:
                    conn.execute("""INSERT INTO monitor_states
                        (method,watch_id,state,last_confirmed,ok_count,bad_count,last_sample,last_check,reason,target_json,label)
                        VALUES(?,?,'unknown','',0,0,'','','not_checked',?,?)""",
                        (*watch.key(), spec, watch.label or ""))
                elif old["target_json"] != spec:
                    conn.execute("""UPDATE monitor_states SET state='unknown',last_confirmed='',ok_count=0,
                        bad_count=0,last_sample='',last_check='',reason='target_changed',target_json=?,label=?
                        WHERE method=? AND watch_id=?""", (spec,watch.label or "",*watch.key()))
                    conn.execute("DELETE FROM monitor_outbox WHERE method=? AND watch_id=?",watch.key())
                else:
                    conn.execute("UPDATE monitor_states SET label=? WHERE method=? AND watch_id=?",
                                 (watch.label or "",*watch.key()))

    def sample(self, conn: sqlite3.Connection, watch: Watch, last_sample: str) -> tuple[str, str, str]:
        if watch.method == "arp":
            return arp_probe(conn, watch, last_sample)
        if watch.method == "ha_device_tracker":
            outcome, reason, reported = tracker_probe(watch.target)
            if outcome in ("positive", "negative") and reported == last_sample:
                return "skip", "tracker_no_new_report", last_sample
            return outcome, reason, reported
        elif watch.method == "icmp":
            outcome, reason = icmp_probe(watch.target)
        else:
            outcome, reason = tcp_probe(watch.target, watch.port or 0)
        return outcome, reason, datetime.now(timezone.utc).isoformat()

    def observe(self, conn: sqlite3.Connection, watch: Watch,
                outcome: str, reason: str, sample: str, now: str) -> None:
        if outcome == "skip":
            return
        old = conn.execute("SELECT * FROM monitor_states WHERE method=? AND watch_id=?",watch.key()).fetchone()
        if old is None:
            return
        if outcome == "unknown":
            with conn:
                conn.execute("""UPDATE monitor_states SET state='unknown',ok_count=0,bad_count=0,
                    reason=?,last_check=?,last_sample=? WHERE method=? AND watch_id=?""",
                    (reason, now, sample, *watch.key()))
            return
        positive = outcome == "positive"
        ok = old["ok_count"]+1 if positive else 0
        bad = old["bad_count"]+1 if not positive else 0
        confirmed = (positive and ok >= SUCCESSES) or (not positive and bad >= FAILURES)
        new_state = state_value(watch.method, positive) if confirmed else (old["last_confirmed"] or "unknown")
        previous = old["last_confirmed"]
        with conn:
            conn.execute("""UPDATE monitor_states SET state=?,last_confirmed=?,ok_count=?,bad_count=?,
                reason=?,last_check=?,last_sample=? WHERE method=? AND watch_id=?""",
                (new_state, new_state if confirmed else previous, min(ok,SUCCESSES), min(bad,FAILURES),
                 reason,now,sample,*watch.key()))
            if confirmed and previous and previous != new_state:
                suffix = ("reachable" if positive else "unreachable") if watch.method in ("icmp","tcp") else ("present" if positive else "absent")
                payload: dict[str, Any] = {
                    "schema_version": 2, "event_type": "tracked_device_"+suffix,
                    "observed_at": now, "watch_id": watch.watch_id,
                    "check_method": watch.method, "previous": previous, "current": new_state,
                    "reason": reason, "consecutive_successes": ok, "consecutive_failures": bad,
                }
                field = {"icmp":"ip","arp":"mac","ha_device_tracker":"entity_id","tcp":"ip"}[watch.method]
                payload[field] = watch.target
                if watch.port is not None:
                    payload["port"] = watch.port
                if watch.label is not None:
                    payload["label"] = watch.label
                payload["event_id"] = str(uuid5(NAMESPACE_URL,
                    f"dh_network_app:{watch.method}:{watch.watch_id}:{now}:{previous}:{new_state}"))
                encoded = json.dumps(payload,ensure_ascii=False,separators=(",",":"))
                conn.execute("""INSERT OR IGNORE INTO monitor_outbox
                    (event_id,method,watch_id,occurred_at,payload_json)
                    VALUES(?,?,?,?,?)""",
                    (payload["event_id"],watch.method,watch.watch_id,now,encoded))
                conn.execute("INSERT INTO events(event_type,device_id,occurred_at,data_json) VALUES(?,'',?,?)",
                             (payload["event_type"],now,encoded))
                conn.execute("""INSERT OR IGNORE INTO event_delivery_log
                   (event_id,event_type,occurred_at,status,payload_json)
                   VALUES(?,?,?,'queued',?)""",
                   (payload["event_id"],payload["event_type"],now,encoded))
                conn.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 1000)")

    def publish(self, conn: sqlite3.Connection, mqtt_events: Any) -> None:
        if not mqtt_events.connected.is_set():
            self.last_connect = False
            return
        # MQTT may disconnect and reconnect between two 4s worker cycles.
        # A callback-maintained epoch catches even that short gap.
        epoch = getattr(mqtt_events, "connection_epoch", None)
        if not self.last_connect or (epoch is not None and epoch != self.last_connection_epoch):
            self.force_publish = True
            self.published.clear()
        self.last_connection_epoch = epoch
        self.last_connect = True
        tombstones = conn.execute("SELECT method,watch_id FROM monitor_tombstones").fetchall()
        for gone in tombstones:
            method, wid = gone["method"],gone["watch_id"]
            template = Watch(method,wid,"")
            if not self.retained(mqtt_events,template.discovery_topic(),""):
                return
            if not self.retained(mqtt_events,template.state_topic(),""):
                return
            if not self.retained(mqtt_events,template.attrs_topic(),""):
                return
            with conn:
                conn.execute("DELETE FROM monitor_tombstones WHERE method=? AND watch_id=?",(method,wid))
        if self.force_publish:
            for watch in self.watches:
                config = json.dumps(discovery_payload(watch,mqtt_events.version),
                                    ensure_ascii=False,separators=(",",":"))
                if not self.retained(mqtt_events,watch.discovery_topic(),config):
                    return
            self.force_publish = False
        # Retained authoritative states precede transient events.
        for watch in self.watches:
            row = conn.execute("SELECT * FROM monitor_states WHERE method=? AND watch_id=?",watch.key()).fetchone()
            if not row:
                continue
            attrs = {"watch_id": watch.watch_id, "check_method": watch.method,
                     "reason": row["reason"], "last_check": row["last_check"]}
            if watch.label is not None:
                attrs["label"] = watch.label
            if not self.retained(mqtt_events,watch.state_topic(),row["state"]):
                return
            if not self.retained(mqtt_events,watch.attrs_topic(),json.dumps(attrs,ensure_ascii=False)):
                return
        pending = conn.execute("""SELECT event_id,payload_json FROM monitor_outbox
                                  ORDER BY occurred_at,event_id LIMIT 32""").fetchall()
        for event in pending:
            ok=mqtt_events.publish_checked(ROOT+"/event",event["payload_json"],False)
            with conn:
                conn.execute("""UPDATE event_delivery_log SET attempts=attempts+1,
                    status=?,published_at=CASE WHEN ? THEN ? ELSE published_at END
                    WHERE event_id=?""",
                    ("broker_acked" if ok else "retrying",int(ok),
                     datetime.now(timezone.utc).isoformat() if ok else "",event["event_id"]))
                if ok:
                    conn.execute("DELETE FROM monitor_outbox WHERE event_id=?",(event["event_id"],))
            if not ok:
                return

    def cycle(self, conn: sqlite3.Connection, mqtt_events: Any) -> None:
        conn.row_factory = sqlite3.Row
        self.reload()
        self.sync(conn)
        now_mono = time.monotonic()
        for watch in self.watches:
            key = watch.key()
            if now_mono < self.next_due.get(key, 0):
                continue
            self.next_due[key] = now_mono + CHECK_SECONDS[watch.method]
            last = conn.execute("SELECT last_sample FROM monitor_states WHERE method=? AND watch_id=?",key).fetchone()
            try:
                outcome,reason,sample = self.sample(conn,watch,last["last_sample"] if last else "")
            except (OSError, sqlite3.Error, ValueError) as exc:
                LOG.warning("Monitor %s/%s failed: %s",*key,exc)
                outcome,reason,sample = "unknown","monitor_error",datetime.now(timezone.utc).isoformat()
            self.observe(conn,watch,outcome,reason,sample,datetime.now(timezone.utc).isoformat())
        self.publish(conn,mqtt_events)


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3 or sys.argv[1] != "--validate":
            raise ConfigError("usage: monitoring.py --validate <YAML-file>")
        watches = load_config(Path(sys.argv[2]))
        print(f"valid monitoring configuration: {len(watches)} checks")
    except (ConfigError, OSError, UnicodeError) as exc:
        print(f"monitoring config invalid: {exc}", file=sys.stderr)
        sys.exit(2)
