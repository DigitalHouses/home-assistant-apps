"""SQLite storage for stable Zigbee identities and aggregated MQTT activity.

Only minute buckets are persisted, not individual MQTT messages.  The store
never invents missing data or deletes a physical device on Z2M rename.
"""

from __future__ import annotations

import sqlite3
import re
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
"""


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

    def commit_counts(
        self,
        counts: Mapping[tuple[int, str, str], int],
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
