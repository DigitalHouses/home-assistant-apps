"""DH Journal 1.0.0: bounded local, append-only diagnostic events."""
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo
import json
import logging
import re
import sqlite3
import uuid

VERSION = "1.0.0"
LIMIT = 3000
LEVELS = ("debug", "info", "success", "pending", "warning", "error", "lifecycle")
ICONS = dict(zip(LEVELS, ("🔍", "ℹ️", "✅", "⏳", "⚠️", "❌", "🔄")))
ROOT = Path(__file__).parent
LOG = logging.getLogger("dh_journal")
SECRET = re.compile(r"password|passwd|token|secret|credential|authorization|api.?key|cookie", re.I)
CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")


def clean(value):
    # Callers must pass explicit safe facts, never arbitrary requests or credentials.
    if isinstance(value, dict):
        return {str(k)[:80]: "[REDACTED]" if SECRET.search(str(k)) else clean(v)
                for k, v in list(value.items())[:32]}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value[:32]]
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if abs(value) < float("inf") else None
    return str(value).replace("\r", " ").replace("\n", " ")[:500]


class Journal:
    def __init__(self, path, *, product, locales=None, debug=False, clock=None):
        if not CODE.fullmatch(product):
            raise ValueError("Invalid product")
        self.product = product
        self.debug_enabled = debug
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.lock = RLock()
        self.generation = uuid.uuid4().hex
        self.db = None
        self.ram = deque(maxlen=LIMIT)
        self.seq = 0
        self.storage = "sqlite"
        self.messages = {}
        for lang in ("ru", "en"):
            common = json.loads((ROOT / "locales" / (lang + ".json")).read_text())
            common.update((locales or {}).get(lang, {}))
            self.messages[lang] = common
        try:
            self.db = sqlite3.connect(str(path), timeout=.15, check_same_thread=False)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            with self.db:
                self.db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, level TEXT NOT NULL, code TEXT NOT NULL, params TEXT NOT NULL)")
                self._prune()
            self.seq = self.db.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
        except (sqlite3.Error, OSError):
            self._fallback()

    def _prune(self):
        self.db.execute("DELETE FROM events WHERE id < (SELECT id FROM events ORDER BY id DESC LIMIT 1 OFFSET ?)", (LIMIT - 1,))

    @staticmethod
    def _decode(row):
        i, ts, level, code, params = row
        return {"id": i, "ts": ts, "level": level, "code": code, "params": json.loads(params)}

    def _fallback(self):
        if self.db is not None:
            try:
                self.ram.extend(self._decode(r) for r in self.db.execute("SELECT id,ts,level,code,params FROM events ORDER BY id"))
                self.seq = max(self.seq, self.ram[-1]["id"] if self.ram else 0)
            except (sqlite3.Error, ValueError):
                pass
            try:
                self.db.close()
            except sqlite3.Error:
                pass
        self.db = None
        self.storage = "ram"
        self.generation = uuid.uuid4().hex
        LOG.warning("DH Journal SQLite unavailable; RAM only until next restart")

    def record(self, level, code, **params):
        if level == "debug" and not self.debug_enabled:
            return
        if level not in LEVELS or not CODE.fullmatch(code):
            raise ValueError("Invalid journal event")
        ts = self.clock().astimezone(timezone.utc).isoformat(timespec="milliseconds")
        params = clean(params)
        raw = json.dumps(params, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with self.lock:
            if self.db is not None:
                try:
                    with self.db:
                        cur = self.db.execute("INSERT INTO events(ts,level,code,params) VALUES(?,?,?,?)", (ts, level, code, raw))
                        self._prune()
                    self.seq = cur.lastrowid
                    return
                except (sqlite3.Error, OSError):
                    self._fallback()
            self.seq += 1
            self.ram.append({"id": self.seq, "ts": ts, "level": level, "code": code, "params": params})

    def start(self, version):
        self.record("lifecycle", "app_started", version=version, journal=VERSION)

    def stop(self):
        self.record("lifecycle", "app_stopped")

    def clear(self):
        with self.lock:
            if self.db is not None:
                try:
                    with self.db:
                        self.db.execute("DELETE FROM events")
                except (sqlite3.Error, OSError):
                    self._fallback()
            self.ram.clear()
            self.generation = uuid.uuid4().hex
            self.record("info", "journal_cleared")

    def snapshot(self, after=0, generation=None):
        with self.lock:
            if generation != self.generation:
                after = 0
            if self.db is not None:
                try:
                    oldest, newest, count = self.db.execute("SELECT COALESCE(MIN(id),0),COALESCE(MAX(id),0),COUNT(*) FROM events").fetchone()
                    rows = [self._decode(r) for r in self.db.execute("SELECT id,ts,level,code,params FROM events WHERE id>? ORDER BY id", (after,))]
                except (sqlite3.Error, OSError, ValueError):
                    self._fallback()
                    return self.snapshot()
            else:
                count = len(self.ram)
                oldest = self.ram[0]["id"] if count else 0
                newest = self.ram[-1]["id"] if count else 0
                rows = [dict(r) for r in self.ram if r["id"] > after]
            return dict(generation=self.generation, oldest=oldest, newest=newest, count=count,
                        limit=LIMIT, storage=self.storage, rows=rows, version=VERSION)

    def message(self, row, lang):
        template = self.messages.get(lang, self.messages["en"]).get(row["code"])
        if template:
            try:
                return template.format(**row["params"])
            except (KeyError, ValueError):
                pass
        return row["code"] + " " + json.dumps(row["params"], ensure_ascii=False)

    @staticmethod
    def zone(name):
        try:
            return ZoneInfo(name or "UTC")
        except (ValueError, KeyError):
            return timezone.utc

    def export(self, lang, tz):
        zone = self.zone(tz)
        lines = []
        for row in self.snapshot()["rows"]:
            dt = datetime.fromisoformat(row["ts"]).astimezone(zone).isoformat(timespec="milliseconds")
            detail = " | " + json.dumps(row["params"], ensure_ascii=False, separators=(",", ":")) if row["params"] else ""
            lines.append(f"{dt} [{row['level'].upper()}] {ICONS[row['level']]} {self.message(row, lang)}{detail}")
        stamp = self.clock().astimezone(zone).strftime("%Y-%m-%d_%H-%M-%S")
        return self.product + "_" + stamp + ".log", ("\n".join(lines) + "\n").encode("utf-8")

    def close(self):
        with self.lock:
            if self.db is not None:
                self.db.close()
                self.db = None


def _level(name):
    return lambda self, code, **params: self.record(name, code, **params)


for _name in LEVELS:
    setattr(Journal, _name, _level(_name))
