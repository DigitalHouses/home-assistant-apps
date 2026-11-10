from __future__ import annotations

import re
import threading

from .collectors.cooling import FanSnapshot
from .state_store import StateStore

MAX_FAN_RPM = 30000
_FAN_ID = re.compile(r"^[a-z0-9_]+$")


class FanMaxRpmRegistry:
    """User-entered 100% RPM values. Never writes to fan hardware."""

    def __init__(self, state_store: StateStore) -> None:
        self.state_store = state_store
        self._lock = threading.RLock()

    def get(self, fan_id: str) -> int:
        with self._lock:
            values = self.state_store.load().get("fans", {})
            if not isinstance(values, dict):
                return 0
            value = values.get(fan_id, 0)
            return value if type(value) is int and 0 <= value <= MAX_FAN_RPM else 0

    def set(self, fan_id: str, max_rpm: int) -> bool:
        if not isinstance(fan_id, str) or not _FAN_ID.fullmatch(fan_id):
            raise ValueError("invalid fan ID")
        if type(max_rpm) is not int or not 0 <= max_rpm <= MAX_FAN_RPM:
            raise ValueError("max RPM must be an integer from 0 to 30000")
        with self._lock:
            data = self.state_store.load()
            values = data.get("fans")
            fans = dict(values) if isinstance(values, dict) else {}
            if fans.get(fan_id, 0) == max_rpm:
                return False
            if max_rpm == 0:
                fans.pop(fan_id, None)
            else:
                fans[fan_id] = max_rpm
            data["fans"] = fans
            data["schema_version"] = 1
            self.state_store.save(data)
            return True

    def presentation(self, fan: FanSnapshot) -> dict[str, int | None]:
        maximum = self.get(fan.fan_id)
        percent = None
        if maximum and fan.rpm is not None:
            percent = min(100, max(0, int(fan.rpm / maximum * 100 + 0.5)))
        return {"max_rpm": maximum, "speed_percent": percent}
