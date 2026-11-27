"""Read-only access to the live Home Assistant Recorder SQLite database."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from config import DatabaseConfig, SQLITE_PATH
from db.base import DatabaseAdapter


class SQLiteAdapter(DatabaseAdapter):
    def __init__(self, config: DatabaseConfig, path: Path = SQLITE_PATH,
                 query_timeout: float = 2.0) -> None:
        self.config = config
        self.path = Path(path)
        self.query_timeout = query_timeout

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        # No immutable/nolock: SQLite must read the live WAL and coordinate with
        # the writer. A read-only mount prevents creation/modification of sidecars.
        deadline = time.monotonic() + self.query_timeout
        connection = sqlite3.connect(
            self.path.resolve().as_uri() + "?mode=ro", uri=True,
            timeout=min(0.25, self.query_timeout), isolation_level=None,
        )
        try:
            connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            connection.execute("PRAGMA query_only=ON")
            return connection.execute(sql, params).fetchall()
        finally:
            connection.close()

    def _one(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        rows = self._rows(sql, params)
        return rows[0][0] if rows else None

    def fast_metrics(self, hour_cutoff: float | None = None) -> dict[str, Any]:
        return {"db_last_ts": self._one("SELECT MAX(last_updated_ts) FROM states"), **self.file_metrics()}

    def medium_metrics(self, current_hour_start: float, today_start: float,
                       period_end: float) -> dict[str, Any]:
        hour, today = self._rows(
            "SELECT COALESCE(SUM(CASE WHEN last_updated_ts >= ? THEN 1 ELSE 0 END), 0), "
            "COUNT(*) FROM states WHERE last_updated_ts >= ? AND last_updated_ts < ?",
            (current_hour_start, today_start, period_end),
        )[0]
        return {"records_current_hour": hour, "records_today": today, **self.file_metrics()}

    def file_metrics(self) -> dict[str, int]:
        size = self.path.stat().st_size
        # Account for physical WAL footprint separately from the database file.
        try:
            wal_size = Path(str(self.path) + "-wal").stat().st_size
        except FileNotFoundError:
            wal_size = 0
        return {"db_size_bytes": size, "db_wal_size_bytes": wal_size}

    def slow_metrics(self) -> dict[str, Any]:
        return {
            "db_start_ts": self._one("SELECT MIN(last_updated_ts) FROM states"),
            "records_total": self._one("SELECT COUNT(*) FROM states"),
        }

    def static_metrics(self) -> dict[str, Any]:
        return {"db_name": self.path.name, "db_version": self._one("SELECT sqlite_version()")}

    def top_entities(self, since_ts: float | None, until_ts: float | None,
                     limit: int) -> list[tuple[str, int, float]]:
        where = ""
        params: tuple[Any, ...] = (limit,)
        if since_ts is not None and until_ts is not None:
            where = " WHERE last_updated_ts >= ? AND last_updated_ts < ?"
            params = (since_ts, until_ts, limit)
        # Aggregate using Recorder's metadata/timestamp indexes before joining
        # names, instead of looking up the entity name for every state row.
        rows = self._rows(
            "WITH counts AS (SELECT metadata_id, COUNT(*) AS n FROM states"
            + where + " GROUP BY metadata_id) "
            "SELECT sm.entity_id, SUM(counts.n) AS records, "
            "ROUND(SUM(counts.n) * 100.0 / SUM(SUM(counts.n)) OVER (), 2) AS share_percent "
            "FROM counts JOIN states_meta AS sm ON sm.metadata_id = counts.metadata_id "
            "GROUP BY sm.entity_id ORDER BY records DESC, sm.entity_id ASC LIMIT ?",
            params,
        )
        return [(str(entity), int(count), float(share)) for entity, count, share in rows]

    def data_directory(self) -> str:
        return str(self.path.parent)
