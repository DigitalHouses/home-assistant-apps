"""One HA-owned timezone, cached across restarts. Never a sync admission gate."""
from datetime import datetime
import logging
import os
from pathlib import Path
import tempfile
from threading import Lock
from zoneinfo import ZoneInfo

LOG = logging.getLogger("dh_sync.timezone")


def valid_zone(value):
    if not isinstance(value, str) or not value or len(value) > 128:
        return None
    try:
        ZoneInfo(value)
    except (ValueError, KeyError, OSError):
        return None
    return value


class HATimezone:
    def __init__(self, resolve, cache=Path("/data/ha_timezone")):
        self.resolve = resolve
        self.cache = Path(cache)
        self.lock = Lock()
        try:
            self.last = valid_zone(self.cache.read_text(encoding="utf-8").strip())
        except (OSError, UnicodeError):
            self.last = None

    def snapshot(self):
        # One immutable value; no HA request or filesystem I/O from Ingress.
        last = self.last
        return last or "UTC", last is None

    def refresh(self):
        with self.lock:
            try:
                zone = valid_zone(self.resolve())
            except Exception:
                zone = None
            if zone is None:
                if self.last is None:
                    LOG.debug("HA timezone unavailable; UTC fallback")
                return self.snapshot()
            changed = self.last != zone
            self.last = zone
            if changed:
                LOG.info("HA timezone: %s", zone)
            # Retry failed persistence on the next existing sync.
            try:
                if self.cache.exists() and self.cache.read_text(encoding="utf-8").strip() == zone:
                    return self.snapshot()
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.cache.parent,
                                                 prefix=".ha-timezone-", delete=False) as stream:
                    temporary = Path(stream.name)
                    try:
                        stream.write(zone + "\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                    except Exception:
                        temporary.unlink(missing_ok=True)
                        raise
                try:
                    os.replace(temporary, self.cache)
                finally:
                    temporary.unlink(missing_ok=True)
            except (OSError, UnicodeError):
                LOG.warning("Unable to persist HA timezone; current value retained in memory")
            return self.snapshot()


class HAFormatter(logging.Formatter):
    def __init__(self, source):
        super().__init__("%(asctime)s %(levelname)s %(message)s")
        self.source = source

    def formatTime(self, record, datefmt=None):
        zone, fallback = self.source.snapshot()
        stamp = datetime.fromtimestamp(record.created, ZoneInfo(zone)).isoformat(timespec="milliseconds")
        return stamp + (" (UTC fallback)" if fallback else "")
