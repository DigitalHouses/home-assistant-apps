"""SQLite storage for stable Zigbee identities and aggregated MQTT activity.

Only minute buckets are persisted, not individual MQTT messages.  The store
never invents missing data or deletes a physical device on Z2M rename.
"""

from __future__ import annotations

import sqlite3
import json
import re
import ipaddress
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .core import Device


_SCHEMA = """
CREATE TABLE IF NOT EXISTS networks (
    coordinator_ieee TEXT PRIMARY KEY,
    network_id TEXT NOT NULL UNIQUE,
    base_topic TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    last_seen INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    ieee_address TEXT PRIMARY KEY,
    network_id TEXT NOT NULL,
    friendly_name TEXT NOT NULL,
    model TEXT,
    manufacturer TEXT,
    device_type TEXT,
    observed_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS message_minutes (
    bucket_start INTEGER NOT NULL,
    network_id TEXT NOT NULL,
    ieee_address TEXT NOT NULL,
    messages INTEGER NOT NULL CHECK(messages >= 0),
    PRIMARY KEY (bucket_start, network_id, ieee_address)
);
CREATE INDEX IF NOT EXISTS message_minutes_device_idx
    ON message_minutes (ieee_address, bucket_start);
CREATE TABLE IF NOT EXISTS device_mqtt_activity (
    network_id TEXT NOT NULL,
    ieee_address TEXT NOT NULL,
    last_message_epoch INTEGER NOT NULL CHECK(last_message_epoch >= 0),
    PRIMARY KEY (network_id, ieee_address)
);
-- Durable, bounded-in-frequency transitions; no per-MQTT-packet rows.
-- Object identity is the immutable coordinator network ID plus device IEEE.
CREATE TABLE IF NOT EXISTS incidents (
    incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK(kind IN ('device_offline', 'zigbee2mqtt_offline')),
    network_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    object_name TEXT NOT NULL,
    first_observed_at INTEGER NOT NULL CHECK(first_observed_at >= 0),
    started_at INTEGER CHECK(started_at >= 0),
    resolved_at INTEGER CHECK(resolved_at >= 0),
    resolution_source TEXT CHECK(resolution_source IN ('live_transition', 'reconciliation'))
);
-- Safe metadata snapshot from bridge/info (not a raw config).
CREATE TABLE IF NOT EXISTS network_infrastructure (
    network_id TEXT PRIMARY KEY NOT NULL,
    metadata_json TEXT NOT NULL,
    received_at INTEGER NOT NULL CHECK(received_at >= 0)
);
-- Passport-free per-network user policy. No executable permissions implied.
CREATE TABLE IF NOT EXISTS network_agent_policy (
    network_id TEXT PRIMARY KEY NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    critical INTEGER NOT NULL DEFAULT 0 CHECK(critical IN (0,1)),
    hardware_model TEXT NOT NULL DEFAULT '',
    management_host TEXT NOT NULL DEFAULT '',
    healer_method TEXT NOT NULL DEFAULT 'disabled'
        CHECK(healer_method IN ('disabled','addon_restart','power_cycle')),
    addon_slug TEXT NOT NULL DEFAULT '',
    power_switch TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS network_problem_settings (
    network_id TEXT PRIMARY KEY NOT NULL,
    auto_rpm_threshold INTEGER NOT NULL DEFAULT 1 CHECK(auto_rpm_threshold IN (0,1)),
    manual_rpm_threshold INTEGER NOT NULL DEFAULT 10 CHECK(manual_rpm_threshold BETWEEN 0 AND 10000)
);
-- Recorder-independent per-network RPM at one row per observed minute.
-- Missing observation differs from an observed zero; no synthetic gap filling.
CREATE TABLE IF NOT EXISTS network_rpm_minutes (
    network_id TEXT NOT NULL,
    minute_start INTEGER NOT NULL CHECK(minute_start >= 0),
    rpm REAL,
    valid INTEGER NOT NULL CHECK(valid IN (0,1)),
    healthy INTEGER NOT NULL CHECK(healthy IN (0,1)),
    PRIMARY KEY(network_id,minute_start)
);
CREATE TABLE IF NOT EXISTS network_rpm_baselines (
    network_id TEXT PRIMARY KEY NOT NULL,
    baseline REAL NOT NULL CHECK(baseline >= 0),
    updated_at INTEGER NOT NULL CHECK(updated_at >= 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS incidents_one_open_per_object
    ON incidents(kind, network_id, object_id) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS incidents_recent_closed
    ON incidents(resolved_at DESC) WHERE resolved_at IS NOT NULL;
"""


def _incident_iso(epoch: object) -> str | None:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch is not None else None


class ActivityStore:
    """Installation-specific persistent data; place file under HAOS /data."""

    def __init__(self, db_path: Path | str) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # MQTT callbacks and the aggregation worker share this connection.
        # MonitorService serializes every operation with a single RLock.
        self.conn = sqlite3.connect(str(self.path), timeout=10.0, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        # Earlier installations have a CHECK(1..10000); rebuild this small
        # settings table in place, retaining every site's AUTO/MANUAL choices.
        ddl_row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='network_problem_settings'"
        ).fetchone()
        if ddl_row and "BETWEEN 1 AND 10000" in str(ddl_row[0]):
            with self.conn:
                self.conn.execute(
                    "ALTER TABLE network_problem_settings RENAME TO "
                    "network_problem_settings_legacy"
                )
                self.conn.execute(
                    "CREATE TABLE network_problem_settings ("
                    "network_id TEXT PRIMARY KEY NOT NULL,"
                    "auto_rpm_threshold INTEGER NOT NULL DEFAULT 1 "
                    "CHECK(auto_rpm_threshold IN (0,1)),"
                    "manual_rpm_threshold INTEGER NOT NULL DEFAULT 10 "
                    "CHECK(manual_rpm_threshold BETWEEN 0 AND 10000))"
                )
                self.conn.execute(
                    "INSERT INTO network_problem_settings "
                    "SELECT * FROM network_problem_settings_legacy"
                )
                self.conn.execute("DROP TABLE network_problem_settings_legacy")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ActivityStore":
        return self

    def __exit__(self, _type: object, _value: object, _trace: object) -> None:
        self.close()

    def known_networks(self) -> tuple["Network", ...]:
        from .core import Network

        records = self.conn.execute(
            "SELECT network_id,base_topic,display_name FROM networks "
            "ORDER BY network_id"
        ).fetchall()
        return tuple(Network(network_id, base, name) for network_id, base, name in records)

    def register_network(
        self, coordinator_ieee: str, base_topic: str, *,
        observed_at: int, preferred_id: str | None = None,
    ) -> tuple["Network", bool]:
        """Resolve coordinator IEEE into a stable logical ID and persist its topic.

        The optional preferred_id migrates a formerly manually configured
        network only if its base topic agrees with the discovered coordinator.
        """
        from .core import Network

        if not isinstance(coordinator_ieee, str) or not re.fullmatch(
            r"0x[0-9a-f]{16}", coordinator_ieee
        ):
            raise ValueError("invalid coordinator IEEE")
        if not isinstance(observed_at, int) or isinstance(observed_at, bool) or observed_at < 0:
            raise ValueError("invalid observed_at")
        if not isinstance(base_topic, str) or not base_topic:
            raise ValueError("invalid base_topic")
        row = self.conn.execute(
            "SELECT network_id, base_topic, display_name FROM networks "
            "WHERE coordinator_ieee=?", (coordinator_ieee,)
        ).fetchone()
        existing = self.conn.execute(
            "SELECT coordinator_ieee, network_id FROM networks WHERE base_topic=?",
            (base_topic,),
        ).fetchone()
        if existing and existing[0] != coordinator_ieee:
            raise ValueError("coordinator changed at existing base_topic; requires deliberate migration")
        if row:
            network_id, old_base, display_name = row
            if old_base != base_topic and display_name == old_base:
                display_name = base_topic
        else:
            network_id = preferred_id or "z2m_" + coordinator_ieee[2:]
            old_base = None
            display_name = base_topic
            if self.conn.execute(
                "SELECT 1 FROM networks WHERE network_id=?", (network_id,)
            ).fetchone():
                raise ValueError("network_id collision")
        changed = old_base != base_topic
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO networks(coordinator_ieee,network_id,base_topic,display_name,last_seen)
                VALUES (?,?,?,?,?)
                ON CONFLICT(coordinator_ieee) DO UPDATE SET
                  base_topic=excluded.base_topic,
                  display_name=excluded.display_name,
                  last_seen=excluded.last_seen
                """,
                (coordinator_ieee, network_id, base_topic, display_name, observed_at),
            )
        return Network(network_id, base_topic, display_name), changed

    def upsert_inventory(self, devices: tuple[Device, ...], *, observed_at: int) -> None:
        if not isinstance(observed_at, int) or isinstance(observed_at, bool) or observed_at < 0:
            raise ValueError("observed_at must be a positive Unix timestamp")
        rows = [
            (d.ieee_address, d.network_id, d.friendly_name, d.model,
             d.manufacturer, d.device_type, observed_at)
            for d in devices
        ]
        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO devices
                  (ieee_address, network_id, friendly_name, model,
                   manufacturer, device_type, observed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ieee_address) DO UPDATE SET
                  network_id=excluded.network_id,
                  friendly_name=excluded.friendly_name,
                  model=excluded.model,
                  manufacturer=excluded.manufacturer,
                  device_type=excluded.device_type,
                  observed_at=excluded.observed_at
                """,
                rows,
            )

    def observe_incident(
        self, *, kind: str, network_id: str, object_id: str,
        object_name: str, offline: bool, observed_at: int,
        live_transition: bool,
    ) -> bool:
        """Reconcile one *confirmed* Z2M state with persisted incidents.

        A retained offline snapshot establishes a problem but NOT its onset.
        Reconciliation after a restart never fabricates transition timestamps.
        Return whether durable state changed (open/closed), not an event trigger.
        """
        if kind not in ("device_offline", "zigbee2mqtt_offline"):
            raise ValueError("unsupported incident kind")
        if any(not isinstance(v, str) or not v
               for v in (network_id, object_id, object_name)):
            raise ValueError("incident identity and name are required")
        if not isinstance(offline, bool) or not isinstance(live_transition, bool):
            raise ValueError("incident states must be bool")
        if not isinstance(observed_at, int) or isinstance(observed_at, bool) or observed_at < 0:
            raise ValueError("invalid incident timestamp")
        with self.conn:
            existing = self.conn.execute(
                "SELECT incident_id FROM incidents WHERE "
                "kind=? AND network_id=? AND object_id=? AND resolved_at IS NULL",
                (kind, network_id, object_id),
            ).fetchone()
            if offline:
                if existing:
                    self.conn.execute(
                        "UPDATE incidents SET object_name=? WHERE incident_id=? "
                        "AND object_name<>?",
                        (object_name, existing[0], object_name),
                    )
                    return False
                self.conn.execute(
                    "INSERT INTO incidents(kind,network_id,object_id,object_name,"
                    "first_observed_at,started_at) VALUES (?,?,?,?,?,?)",
                    (kind, network_id, object_id, object_name, observed_at,
                     observed_at if live_transition else None),
                )
                return True
            if existing is None:
                return False
            self.conn.execute(
                "UPDATE incidents SET resolved_at=?, resolution_source=? "
                "WHERE incident_id=?",
                (observed_at, "live_transition" if live_transition
                 else "reconciliation", existing[0]),
            )
            return True

    def incident_history(self, *, open_limit: int = 40,
                         recent_limit: int = 20) -> tuple[list[dict[str, object]],
                                                         list[dict[str, object]], int]:
        """Persisted history, never a misleading state derived from HA Recorder."""
        def as_dict(row: tuple[object, ...]) -> dict[str, object]:
            incident_id, kind, network, object_id, original_name, first, started, ended, source = row
            return {
                "incident_id": incident_id,
                "kind": kind,
                "network_id": network,
                "object_id": object_id,
                "ieee_address": object_id if kind == "device_offline" else None,
                "name": original_name,
                "first_observed_at": _incident_iso(first),
                "started_at": _incident_iso(started),
                "resolved_at": _incident_iso(ended),
                "resolution_source": source,
                "duration_seconds": (
                    max(0, ended - started)
                    if ended is not None and started is not None
                    and source == "live_transition"
                    else None
                ),
            }

        total = int(self.conn.execute(
            "SELECT COUNT(*) FROM incidents WHERE resolved_at IS NULL"
        ).fetchone()[0])
        cols = ("incident_id,kind,network_id,object_id,object_name,"
                "first_observed_at,started_at,resolved_at,resolution_source")
        active = [
            as_dict(row) for row in self.conn.execute(
                f"SELECT {cols} FROM incidents WHERE resolved_at IS NULL "
                "ORDER BY first_observed_at DESC, incident_id DESC LIMIT ?",
                (open_limit,),
            )
        ]
        closed = [
            as_dict(row) for row in self.conn.execute(
                f"SELECT {cols} FROM incidents WHERE resolved_at IS NOT NULL "
                "ORDER BY resolved_at DESC, incident_id DESC LIMIT ?",
                (recent_limit,),
            )
        ]
        return active, closed, total

    def coordinator_ieee(self, network_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT coordinator_ieee FROM networks WHERE network_id=?", (network_id,),
        ).fetchone()
        return row[0] if row else None

    def network_infrastructure(self, network_id: str) -> dict[str, object] | None:
        row = self.conn.execute(
            "SELECT metadata_json, received_at FROM network_infrastructure "
            "WHERE network_id=?", (network_id,),
        ).fetchone()
        return {"data": json.loads(row[0]), "received_at": _incident_iso(row[1])} if row else None

    def save_network_infrastructure(
        self, network_id: str, *, data: dict[str, object], received_at: int,
    ) -> None:
        if not isinstance(network_id, str) or not network_id:
            raise ValueError("network_id is required")
        if type(received_at) is not int or received_at < 0 or not isinstance(data, dict):
            raise ValueError("invalid infrastructure snapshot")
        content = json.dumps(data, separators=(",", ":"), sort_keys=True)
        if len(content) > 4096:
            raise ValueError("infrastructure metadata too large")
        with self.conn:
            self.conn.execute(
                "INSERT INTO network_infrastructure(network_id,metadata_json,received_at) "
                "VALUES(?,?,?) ON CONFLICT(network_id) DO UPDATE SET "
                "metadata_json=excluded.metadata_json,received_at=excluded.received_at "
                "WHERE metadata_json<>excluded.metadata_json OR received_at<>excluded.received_at",
                (network_id, content, received_at),
            )

    @staticmethod
    def default_agent_policy() -> dict[str, object]:
        return {
            "display_name": "", "critical": False,
            "hardware_model": "", "management_host": "",
            "healer_method": "disabled", "addon_slug": "", "power_switch": "",
        }

    def network_agent_policy(self, network_id: str) -> dict[str, object]:
        if not isinstance(network_id, str) or not network_id:
            raise ValueError("network_id required")
        row = self.conn.execute(
            "SELECT display_name,critical,hardware_model,management_host,"
            "healer_method,addon_slug,power_switch FROM network_agent_policy "
            "WHERE network_id=?", (network_id,),
        ).fetchone()
        if row is None:
            return self.default_agent_policy()
        return {
            "display_name": row[0], "critical": bool(row[1]),
            "hardware_model": row[2], "management_host": row[3],
            "healer_method": row[4], "addon_slug": row[5],
            "power_switch": row[6],
        }

    def update_network_agent_policy(
        self, network_id: str, key: str, value: str | bool,
    ) -> dict[str, object]:
        """Validate one HA UI field; NO Supervisor, Zigbee or power operations."""
        if not isinstance(network_id, str) or not network_id:
            raise ValueError("network_id required")
        fields = (
            "display_name", "critical", "hardware_model", "management_host",
            "healer_method", "addon_slug", "power_switch",
        )
        if key not in fields:
            raise ValueError("unknown agent policy field")
        if key == "critical":
            if type(value) is not bool:
                raise ValueError("critical must be boolean")
        else:
            if not isinstance(value, str):
                raise ValueError("agent policy field must be string")
            if key in ("display_name", "hardware_model"):
                if len(value) > 64 or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
                    raise ValueError("invalid display name or hardware model")
                value = value.strip()
            elif key == "management_host":
                if value:
                    if len(value) > 253 or value != value.strip() or any(
                        ch in value for ch in "/\\@?#:\r\n "
                    ):
                        # IPv6 literals are accepted below, not URL-like values.
                        if ":" not in value or any(ch in value for ch in "/\\@?#\r\n "):
                            raise ValueError("management host must be IP or DNS")
                    try:
                        ipaddress.ip_address(value)
                    except ValueError:
                        if not re.fullmatch(
                            r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", value
                        ) or len(value) > 253 or ".." in value or ":" in value:
                            raise ValueError("management host must be IP or DNS")
            elif key == "healer_method":
                if value not in ("disabled", "addon_restart", "power_cycle"):
                    raise ValueError("unsupported recovery method")
            elif key == "addon_slug":
                if value and (len(value) > 96 or not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", value)):
                    raise ValueError("invalid Supervisor app slug")
            elif key == "power_switch":
                if value and (len(value) > 128 or not re.fullmatch(r"switch\.[a-z0-9_]+", value)):
                    raise ValueError("invalid switch entity id")
        previous = self.network_agent_policy(network_id)
        previous[key] = value
        with self.conn:
            # Existing auto-discovery identity is required, not an arbitrary fake agent.
            if not self.conn.execute(
                "SELECT 1 FROM networks WHERE network_id=?", (network_id,)
            ).fetchone():
                raise ValueError("unknown network identity")
            self.conn.execute(
                "INSERT INTO network_agent_policy("
                "network_id,display_name,critical,hardware_model,management_host,"
                "healer_method,addon_slug,power_switch) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(network_id) DO UPDATE SET "
                "display_name=excluded.display_name,critical=excluded.critical,"
                "hardware_model=excluded.hardware_model,"
                "management_host=excluded.management_host,"
                "healer_method=excluded.healer_method,"
                "addon_slug=excluded.addon_slug,power_switch=excluded.power_switch",
                (network_id, previous["display_name"], int(previous["critical"]),
                 previous["hardware_model"], previous["management_host"],
                 previous["healer_method"], previous["addon_slug"],
                 previous["power_switch"]),
            )
        return previous

    def network_problem_settings(self, network_id: str) -> tuple[bool, int]:
        row = self.conn.execute(
            "SELECT auto_rpm_threshold,manual_rpm_threshold "
            "FROM network_problem_settings WHERE network_id=?", (network_id,)
        ).fetchone()
        return (bool(row[0]), int(row[1])) if row else (True, 10)

    def update_network_problem_settings(
        self, network_id: str, *, auto: bool | None = None,
        threshold: int | None = None,
    ) -> tuple[bool, int]:
        if not isinstance(network_id, str) or not network_id:
            raise ValueError("network_id required")
        if auto is not None and not isinstance(auto, bool):
            raise ValueError("auto must be boolean")
        if threshold is not None and (
            type(threshold) is not int or not 0 <= threshold <= 10000
        ):
            raise ValueError("RPM threshold must be integer 0..10000")
        old_auto, old_threshold = self.network_problem_settings(network_id)
        effective_auto = old_auto if auto is None else auto
        effective_threshold = old_threshold if threshold is None else threshold
        with self.conn:
            self.conn.execute(
                "INSERT INTO network_problem_settings"
                "(network_id,auto_rpm_threshold,manual_rpm_threshold) VALUES (?,?,?) "
                "ON CONFLICT(network_id) DO UPDATE SET "
                "auto_rpm_threshold=excluded.auto_rpm_threshold,"
                "manual_rpm_threshold=excluded.manual_rpm_threshold",
                (network_id, int(effective_auto), effective_threshold),
            )
        return effective_auto, effective_threshold

    def network_message_minutes(
        self, network_id: str, *, from_epoch: int, until_epoch: int,
    ) -> dict[int, int]:
        if from_epoch < 0 or until_epoch <= from_epoch:
            raise ValueError("invalid minute range")
        return {
            int(epoch): int(count)
            for epoch, count in self.conn.execute(
                "SELECT bucket_start,SUM(messages) FROM message_minutes "
                "WHERE network_id=? AND bucket_start>=? AND bucket_start<? "
                "GROUP BY bucket_start",
                (network_id, from_epoch, until_epoch),
            )
        }

    def last_mqtt_messages(self) -> dict[tuple[str, str], int]:
        """Actual non-retained MQTT observations, NOT Zigbee RF last_seen."""
        return {
            (network_id, ieee): int(epoch)
            for network_id, ieee, epoch in self.conn.execute(
                "SELECT network_id, ieee_address, last_message_epoch "
                "FROM device_mqtt_activity"
            )
        }

    def commit_counts(
        self,
        counts: Mapping[tuple[int, str, str], int],
        *,
        last_messages: Mapping[tuple[str, str], int] | None = None,
    ) -> None:
        """Atomic batch UPSERT; caller acknowledges in-memory counts only after commit.

        Each incoming message already has an observed UTC minute bucket.
        """
        rows = []
        for (bucket, network_id, ieee), count in counts.items():
            if (
                not isinstance(bucket, int) or isinstance(bucket, bool)
                or bucket < 0 or bucket % 60 != 0
            ):
                raise ValueError("invalid UTC minute bucket")
            if not isinstance(network_id, str) or not network_id:
                raise ValueError("invalid network id")
            if not isinstance(ieee, str) or not ieee.startswith("0x"):
                raise ValueError("invalid IEEE")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("count must be nonnegative integer")
            if count:
                rows.append((bucket, network_id, ieee, count))
        recent = []
        for (network_id, ieee), epoch in (last_messages or {}).items():
            if not isinstance(network_id, str) or not network_id:
                raise ValueError("invalid MQTT activity network id")
            if not isinstance(ieee, str) or not re.fullmatch(r"0x[0-9a-f]{16}", ieee):
                raise ValueError("invalid MQTT activity IEEE")
            if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
                raise ValueError("invalid MQTT activity timestamp")
            recent.append((network_id, ieee, epoch))
        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO message_minutes(bucket_start, network_id, ieee_address, messages)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(bucket_start, network_id, ieee_address)
                DO UPDATE SET messages=message_minutes.messages+excluded.messages
                """,
                rows,
            )
            self.conn.executemany(
                """
                INSERT INTO device_mqtt_activity(network_id, ieee_address, last_message_epoch)
                VALUES (?, ?, ?)
                ON CONFLICT(network_id, ieee_address) DO UPDATE SET
                  last_message_epoch=MAX(
                    device_mqtt_activity.last_message_epoch, excluded.last_message_epoch
                  )
                """,
                recent,
            )

    def rpm_baseline(self, network_id: str) -> float | None:
        row = self.conn.execute(
            "SELECT baseline FROM network_rpm_baselines WHERE network_id=?",
            (network_id,),
        ).fetchone()
        return float(row[0]) if row else None

    def save_rpm_baseline(self, network_id: str, baseline: float, *, epoch: int) -> None:
        import math
        if not math.isfinite(baseline) or baseline < 0 or epoch < 0:
            raise ValueError("invalid trusted RPM baseline")
        with self.conn:
            self.conn.execute(
                "INSERT INTO network_rpm_baselines(network_id,baseline,updated_at) "
                "VALUES (?,?,?) ON CONFLICT(network_id) DO UPDATE SET "
                "baseline=excluded.baseline,updated_at=excluded.updated_at",
                (network_id, baseline, epoch),
            )

    def record_rpm_minute(
        self, network_id: str, *, minute_start: int,
        rpm: float | None, healthy: bool,
    ) -> None:
        """One bounded sample/minute, not an MQTT-packet log."""
        import math
        if minute_start < 0 or minute_start % 60:
            raise ValueError("invalid minute_start")
        if rpm is not None and (not math.isfinite(rpm) or rpm < 0):
            raise ValueError("invalid RPM sample")
        with self.conn:
            self.conn.execute(
                "INSERT INTO network_rpm_minutes"
                "(network_id,minute_start,rpm,valid,healthy) VALUES (?,?,?,?,?) "
                "ON CONFLICT(network_id,minute_start) DO UPDATE SET "
                "rpm=excluded.rpm,valid=excluded.valid,healthy=excluded.healthy",
                (network_id,minute_start,rpm,int(rpm is not None),
                 int(healthy and rpm is not None)),
            )

    def healthy_hour_baseline(
        self, network_id: str, *, until_epoch: int,
    ) -> float | None:
        """Minimum *complete healthy* UTC hour in the last 24 finished hours."""
        until = until_epoch - until_epoch % 3600
        start = max(0, until - 24 * 3600)
        rows = self.conn.execute(
            "SELECT minute_start,rpm,valid,healthy FROM network_rpm_minutes "
            "WHERE network_id=? AND minute_start>=? AND minute_start<? "
            "ORDER BY minute_start", (network_id,start,until),
        ).fetchall()
        hours: dict[int,list[tuple[int,float | None,int,int]]] = {}
        for minute,rpm,valid,healthy in rows:
            hours.setdefault(int(minute)//3600, []).append(
                (int(minute),rpm,int(valid),int(healthy))
            )
        candidates = []
        for hour, samples in hours.items():
            if (len(samples) == 60 and
                    {m for m,_,_,_ in samples} ==
                    set(range(hour*3600,(hour+1)*3600,60)) and
                    all(valid and healthy and rpm is not None
                        for _,rpm,valid,healthy in samples)):
                candidates.append(sum(float(rpm) for _,rpm,_,_ in samples) / 60)
        return round(min(candidates),2) if candidates else None

    def weekly_rpm_summary(
        self, network_id: str, *, until_epoch: int,
    ) -> dict[str, object]:
        """168 hourly and seven contiguous 24h summaries with explicit coverage."""
        end = (until_epoch//3600 + 1) * 3600
        start = max(0,end - 168*3600)
        raw = self.conn.execute(
            "SELECT minute_start,rpm,valid,healthy FROM network_rpm_minutes "
            "WHERE network_id=? AND minute_start>=? AND minute_start<? "
            "ORDER BY minute_start", (network_id,start,end),
        ).fetchall()
        slots: dict[int,list[tuple[float,int]]] = {}
        for minute,rpm,valid,healthy in raw:
            if valid and rpm is not None:
                slots.setdefault(int(minute)//3600*3600,[]).append(
                    (float(rpm),int(healthy))
                )
        def summarize(t: int, values: list[tuple[float,int]],
                      required: int) -> dict[str,object]:
            readings = [value for value,_ in values]
            return {
                "t":t, "min":round(min(readings),2) if readings else None,
                "avg":round(sum(readings)/len(readings),2) if readings else None,
                "max":round(max(readings),2) if readings else None,
                "c":len(values), "ok":len(values)==required and
                all(healthy for _,healthy in values),
            }
        hours = [summarize(t,slots.get(t,[]),60)
                 for t in range(start,end,3600)]
        days = []
        for index in range(7):
            t = start + index*86400
            values = [point for hour in range(t,t+86400,3600)
                      for point in slots.get(hour,[])]
            day = summarize(t,values,1440)
            day["healthy_hours"] = sum(
                1 for hour in hours[index*24:(index+1)*24] if hour["ok"]
            )
            days.append(day)
        return {
            "state":"ready", "network_id":network_id,
            "hours":hours, "days":days,
            "coverage_minutes":sum(int(h["c"]) for h in hours),
            "expected_minutes":10080, "time_basis":"UTC",
            "day_window":"contiguous_24h",
        }

    def top(
        self,
        *,
        from_epoch: int,
        until_epoch: int,
        limit: int = 20,
        network_id: str | None = None,
    ) -> list[dict[str, object]]:
        if (
            not isinstance(from_epoch, int) or not isinstance(until_epoch, int)
            or from_epoch >= until_epoch
        ):
            raise ValueError("invalid top time window")
        if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= 100):
            raise ValueError("top limit must be 1..100")
        # Both bounds operate on whole minute buckets. App publishes complete windows
        # and keeps the current incomplete minute outside the historical ranking.
        query = """
            SELECT m.ieee_address, SUM(m.messages) AS total,
                   COALESCE(d.friendly_name, m.ieee_address),
                   COALESCE(d.network_id, m.network_id)
              FROM message_minutes AS m
              LEFT JOIN devices AS d ON d.ieee_address = m.ieee_address
             WHERE m.bucket_start >= ? AND m.bucket_start < ?
        """
        params: list[object] = [from_epoch, until_epoch]
        if network_id is not None:
            query += " AND m.network_id = ?"
            params.append(network_id)
        query += """
             GROUP BY m.ieee_address
             ORDER BY total DESC, m.ieee_address ASC
             LIMIT ?
        """
        params.append(limit)
        return [
            {
                "ieee_address": ieee,
                "messages": total,
                "name": name,
                "network_id": net,
            }
            for ieee, total, name, net in self.conn.execute(query, params)
        ]

    def first_bucket(self) -> int | None:
        row = self.conn.execute("SELECT MIN(bucket_start) FROM message_minutes").fetchone()
        return row[0] if row is not None else None

    def sum_messages(self, *, from_epoch: int, until_epoch: int) -> int:
        if from_epoch >= until_epoch or from_epoch < 0:
            raise ValueError("invalid message query window")
        row = self.conn.execute(
            "SELECT COALESCE(SUM(messages), 0) FROM message_minutes "
            "WHERE bucket_start >= ? AND bucket_start < ?",
            (from_epoch, until_epoch),
        ).fetchone()
        return int(row[0])

    def trim_minutes(self, *, before_epoch: int) -> int:
        """Retention is called explicitly on aggregated data, never on devices."""
        if not isinstance(before_epoch, int) or before_epoch < 0:
            raise ValueError("invalid retention cutoff")
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM message_minutes WHERE bucket_start < ?", (before_epoch,)
            )
        return cursor.rowcount
