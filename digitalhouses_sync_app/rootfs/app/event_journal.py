"""Bounded local operational history; never a source of sync decisions."""
from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

LOG = logging.getLogger("dh_sync.journal")
DEFAULTS = (30, 10000, 100)
PRODUCT = "digitalhouses_sync_app"


class EventJournal:
    def __init__(self, path=Path("/data/dh_sync.db")):
        self.path = Path(path)
        self.lock = RLock()
        self.ready = False
        self.error = ""
        try:
            with self.lock, closing(self._connect()) as db, db:
                db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, "
                           "ts INTEGER NOT NULL, product TEXT NOT NULL, event TEXT NOT NULL, "
                           "level TEXT NOT NULL, detail TEXT NOT NULL)")
                db.execute("CREATE INDEX IF NOT EXISTS events_ts ON events(ts)")
                db.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), "
                           "days INTEGER NOT NULL, max_rows INTEGER NOT NULL, visible INTEGER NOT NULL)")
                db.execute("INSERT OR IGNORE INTO settings VALUES (1,?,?,?)", DEFAULTS)
                self._prune(db)
            self.ready = True
        except (OSError, sqlite3.Error):
            self.error = "SQLite journal unavailable"
            LOG.exception("Cannot initialize event journal")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=1)

    @staticmethod
    def _settings(db):
        return tuple(db.execute("SELECT days,max_rows,visible FROM settings WHERE id=1").fetchone())

    def _prune(self, db):
        days, max_rows, _ = self._settings(db)
        db.execute("DELETE FROM events WHERE ts < ?", (int(time.time()) - days * 86400,))
        db.execute("DELETE FROM events WHERE id <= (SELECT id FROM events "
                   "ORDER BY id DESC LIMIT 1 OFFSET ?)", (max_rows,))

    def record(self, event, detail="", *, product=PRODUCT, level="info"):
        if not self.ready:
            return
        try:
            with self.lock, closing(self._connect()) as db, db:
                db.execute("INSERT INTO events(ts,product,event,level,detail) VALUES (?,?,?,?,?)",
                           (int(time.time()), str(product)[:200], str(event)[:80],
                            str(level)[:20], str(detail)[:1000]))
                self._prune(db)
            self.error = ""
        except (OSError, sqlite3.Error):
            if not self.error:
                LOG.exception("Cannot write event journal")
            self.error = "SQLite journal write failed"

    def settings(self):
        with self.lock, closing(self._connect()) as db:
            return self._settings(db)

    def configure(self, days, max_rows, visible):
        if not (1 <= days <= 365 and 100 <= max_rows <= 100000 and 10 <= visible <= 1000):
            raise ValueError("Retention: days 1–365; rows 100–100000; visible 10–1000")
        with self.lock, closing(self._connect()) as db, db:
            db.execute("UPDATE settings SET days=?,max_rows=?,visible=? WHERE id=1",
                       (days, max_rows, visible))
            self._prune(db)
        self.record("journal_settings", f"{days} days / {max_rows} rows / {visible} visible")

    def clear(self):
        with self.lock, closing(self._connect()) as db, db:
            db.execute("DELETE FROM events")
        self.record("journal_cleared", "Journal cleared by administrator")

    def facets(self):
        with self.lock, closing(self._connect()) as db:
            return tuple([r[0] for r in db.execute(
                f"SELECT DISTINCT {col} FROM events ORDER BY {col}")]
                for col in ("product", "event"))

    def rows(self, product="", event="", *, all_rows=False):
        with self.lock, closing(self._connect()) as db, db:
            self._prune(db)
            limit = self._settings(db)[1 if all_rows else 2]
            db.row_factory = sqlite3.Row
            result = db.execute("SELECT ts,product,event,level,detail FROM events "
                                "WHERE (?='' OR product=?) AND (?='' OR event=?) "
                                "ORDER BY id DESC LIMIT ?", (product, product, event, event, limit))
            return [dict(row) for row in result]


def display_time(ts):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
