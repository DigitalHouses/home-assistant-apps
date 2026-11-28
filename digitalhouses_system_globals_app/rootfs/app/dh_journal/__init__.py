"""DH Journal 1.0.2: bounded local, append-only diagnostic events."""
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo
import json
import logging
import re
import sqlite3
import time
import uuid

VERSION = "1.0.2"
LIMIT = 3000
MAX_RECORD_BYTES = 8192
MAX_PARAMS_BYTES = MAX_RECORD_BYTES - 256
MAX_DEPTH = 5
MAX_NODES = 128
LEVELS = ("debug", "info", "success", "pending", "warning", "error", "lifecycle")
ICONS = dict(zip(LEVELS, ("🔍", "ℹ️", "✅", "⏳", "⚠️", "❌", "🔄")))
ROOT = Path(__file__).parent
LOG = logging.getLogger("dh_journal")
SECRET = re.compile(r"password|passwd|token|secret|credential|authorization|api.?key|cookie", re.I)
CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")


def clean(value):
    """Bound nesting and work; never stringify arbitrary objects."""
    remaining = MAX_NODES
    def visit(v, depth):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > MAX_DEPTH:
            return "[TRUNCATED]"
        if type(v) is dict:
            out = {}
            for i, (k, item) in enumerate(v.items()):
                if i >= 32 or remaining <= 0:
                    out["_truncated"] = True
                    break
                if type(k) is not str or len(k)>80:
                    out["_truncated"] = True
                    continue
                key = k[:80].encode("utf-8", errors="replace").decode("utf-8")
                out[key] = "[REDACTED]" if SECRET.search(k[:500]) else visit(item, depth+1)
            return out
        if type(v) in (list, tuple):
            out = []
            for i, item in enumerate(v):
                if i >= 32 or remaining <= 0:
                    out.append("[TRUNCATED]")
                    break
                out.append(visit(item, depth+1))
            return out
        if v is None or type(v) is bool:
            return v
        if type(v) is int:
            return v if v.bit_length() <= 256 else "[TRUNCATED]"
        if type(v) is float:
            return v if abs(v) < float("inf") else None
        if type(v) is str:
            return v[:500].replace("\r", " ").replace("\n", " ").encode("utf-8", errors="replace").decode("utf-8")
        return "[UNSUPPORTED]"
    return visit(value, 0)


def encode_params(params):
    """Retain complete safe fields, never partial invalid JSON."""
    safe = clean(params)
    def encode(v):
        return json.dumps(v, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    raw = encode(safe)
    if len(raw.encode("utf-8")) <= MAX_PARAMS_BYTES:
        return safe, raw
    limited = {"_truncated": True}
    for key, value in safe.items():
        if key == "_truncated":
            continue
        limited[key] = value
        if len(encode(limited).encode("utf-8")) > MAX_PARAMS_BYTES:
            del limited[key]
    return limited, encode(limited)


class Journal:
    def __init__(self, path, *, product, product_name=None, locales=None, value_locales=None, icons=None, debug=False, clock=None):
        if not CODE.fullmatch(product):
            raise ValueError("Invalid product")
        self.product = product
        self.product_name = clean(product_name or product)
        self.app_version = None
        self.value_locales = value_locales or {}
        self.icons = icons or {}
        self.debug_enabled = debug
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.lock = RLock()
        self.generation = uuid.uuid4().hex
        self.db = None
        self.ram = deque(maxlen=LIMIT)
        self.seq = 0
        self.storage = "sqlite"
        self.rejected = 0
        self.last_error_log = -float("inf")
        self.messages = {}
        for lang in ("ru", "en"):
            try:
                common = json.loads((ROOT / "locales" / (lang + ".json")).read_text())
                common.update((locales or {}).get(lang, {}))
                self.messages[lang] = common
            except Exception:
                self.messages[lang] = {}
                self.report_failure()
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
                self.ram.extend(self._decode(r) for r in self.db.execute("SELECT id,ts,level,code,params FROM (SELECT id,ts,level,code,params FROM events ORDER BY id DESC LIMIT 3000) ORDER BY id"))
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

    def report_failure(self):
        """Rate-limited internal diagnostics, without event contents."""
        try:
            with self.lock:
                self.rejected += 1
                now = time.monotonic()
                if now - self.last_error_log >= 60:
                    self.last_error_log = now
                    LOG.warning("DH Journal event rejected; application continues (total=%d)", self.rejected)
        except Exception:
            pass

    def record(self, level=None, code=None, /, **params):
        """Best effort: malformed events never interrupt product operations."""
        try:
            return self._record(level, code, params)
        except Exception:
            self.report_failure()
            return False

    def _record(self, level, code, params):
        if type(level) is not str or level not in LEVELS or type(code) is not str or not CODE.fullmatch(code):
            raise ValueError("Invalid journal event")
        if level == "debug" and not self.debug_enabled:
            return False
        params, raw = encode_params(params)
        with self.lock:
            ts = self.clock().astimezone(timezone.utc).isoformat(timespec="milliseconds")
            if self.db is not None:
                try:
                    with self.db:
                        cur = self.db.execute("INSERT INTO events(ts,level,code,params) VALUES(?,?,?,?)", (ts, level, code, raw))
                        self._prune()
                    self.seq = cur.lastrowid
                    return True
                except (sqlite3.Error, OSError):
                    self._fallback()
            self.seq += 1
            self.ram.append({"id": self.seq, "ts": ts, "level": level, "code": code, "params": params})
            return True

    def start(self, version):
        self.app_version = clean(version)
        self.record("lifecycle", "app_started", product_name=self.product_name, version=version, journal=VERSION)

    def stop(self):
        self.record("lifecycle", "app_stopped")

    def clear(self):
        """Acknowledge only after committed disk deletion; refuse RAM-only clear."""
        with self.lock:
            if self.db is None:
                return False
            try:
                ts = self.clock().astimezone(timezone.utc).isoformat(timespec="milliseconds")
                self.db.execute("PRAGMA synchronous=FULL")
                with self.db:
                    self.db.execute("DELETE FROM events")
                    cur = self.db.execute("INSERT INTO events(ts,level,code,params) VALUES(?,?,?,?)",
                                          (ts, "info", "journal_cleared", "{}"))
                self.seq = cur.lastrowid
            except (sqlite3.Error, OSError):
                self._fallback()
                return False
            except Exception:
                self.report_failure()
                return False
            self.ram.clear()
            self.generation = uuid.uuid4().hex
            try:
                self.db.execute("PRAGMA synchronous=NORMAL")
            except (sqlite3.Error, OSError):
                self._fallback()
            return True

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
                        limit=LIMIT, storage=self.storage, rows=rows, version=VERSION, rejected=self.rejected, can_clear=self.db is not None)

    def message(self, row, lang):
        template = self.messages.get(lang, self.messages["en"]).get(row["code"])
        if template:
            try:
                params = dict(row["params"])
                if row["code"] == "app_started":
                    params.setdefault("product_name", self.product_name)
                for key, values in self.value_locales.get(lang, {}).items():
                    if isinstance(params.get(key), str):
                        params[key] = values.get(params[key], params[key])
                return template.format(**params)
            except Exception:
                pass
        return row["code"] + " " + json.dumps(row["params"], ensure_ascii=False)

    def icon(self, row):
        return self.icons.get(row["code"], ICONS.get(row["level"], "ℹ️"))

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
            lines.append(f"{dt} [{row['level'].upper()}] {self.icon(row)} {self.message(row, lang)}{detail}")
        stamp = self.clock().astimezone(zone).strftime("%Y-%m-%d_%H-%M-%S")
        return self.product + "_" + stamp + ".log", ("\n".join(lines) + "\n").encode("utf-8")

    def close(self):
        with self.lock:
            if self.db is not None:
                try:
                    self.db.close()
                except Exception:
                    self.report_failure()
                finally:
                    self.db = None


def _level(name):
    def emit(self, code=None, /, **params):
        try:
            return self._record(name, code, params)
        except Exception:
            self.report_failure()
            return False
    return emit


for _name in LEVELS:
    setattr(Journal, _name, _level(_name))
