"""App-owned HA timezone cache; None explicitly means temporary UTC."""
from pathlib import Path
from zoneinfo import ZoneInfo
import logging
import os
import tempfile
from threading import Lock

LOG = logging.getLogger(__name__)

def valid_zone(value):
    if not isinstance(value, str) or not value or len(value) > 128:
        return None
    try:
        ZoneInfo(value)
    except (ValueError, KeyError, OSError):
        return None
    return value

class HATimezone:
    def __init__(self, cache=Path("/data/ha_timezone")):
        self.cache = Path(cache)
        self.lock = Lock()
        try:
            self.last = valid_zone(self.cache.read_text(encoding="utf-8").strip())
        except (OSError, UnicodeError):
            self.last = None
        self.persisted = self.last

    def snapshot(self):
        return self.last

    def update(self, value):
        zone = valid_zone(value)
        if zone is None:
            return
        with self.lock:
            self.last = zone
            try:
                if self.persisted == zone:
                    return
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
                    self.persisted = zone
                finally:
                    temporary.unlink(missing_ok=True)
            except (OSError, UnicodeError):
                LOG.warning("Unable to persist HA timezone; current value retained in memory")
