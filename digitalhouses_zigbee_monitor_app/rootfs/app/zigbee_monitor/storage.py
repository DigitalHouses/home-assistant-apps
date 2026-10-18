"""SQLite storage for stable Zigbee identities and aggregated MQTT activity.

Only minute buckets are persisted, not individual MQTT messages.  The store
never invents missing data or deletes a physical device on Z2M rename.
"""

from __future__ import annotations

import sqlite3
import re
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
