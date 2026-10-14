"""Pure presence state machine. UNAVAILABLE never means NOT_HOME."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class Status(str, Enum):
    HOME = "home"
    NOT_HOME = "not_home"
    UNAVAILABLE = "unavailable"


class Mode(str, Enum):
    GPS = "gps"
    WIFI = "wifi"
    HYBRID = "hybrid"


def resident_key(user_id: str) -> str:
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("HA user ID is required")
    return hashlib.sha256(user_id.encode()).hexdigest()[:16]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    values = [lat1, lon1, lat2, lon2]
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in values):
        raise ValueError("Invalid coordinates")
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90 and -180 <= lon1 <= 180 and -180 <= lon2 <= 180):
        raise ValueError("Coordinates out of range")
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(a)))


@dataclass
class Resident:
    user_id: str
    name: str
    device_id: str
    tracker: str
    confirmed: Status = Status.UNAVAILABLE
    gps: Status = Status.UNAVAILABLE
    wifi: Status = Status.UNAVAILABLE
    last_gps_at: datetime | None = None
    last_wifi_at: datetime | None = None
    wifi_absent_since: datetime | None = None
    distance: float | None = None
    initialized: bool = False

    @property
    def key(self) -> str:
        return resident_key(self.user_id)


@dataclass
class Engine:
    mode: Mode = Mode.GPS
    wifi_absence_minutes: int = 15
    freshness_seconds: int = 300
    residents: dict[str, Resident] = field(default_factory=dict)

    def __post_init__(self):
        self.mode = Mode(self.mode)
        if not 1 <= self.wifi_absence_minutes <= 120:
            raise ValueError("Invalid wifi absence timeout")
        if not 30 <= self.freshness_seconds <= 3600:
            raise ValueError("Invalid freshness")

    def add(self, user_id: str, name: str, device_id: str, tracker: str, saved: dict | None = None):
        if not user_id or not name or not device_id or not tracker.startswith("device_tracker."):
            raise ValueError("Resident requires HA user ID, name, Mobile Companion device and GPS tracker")
        if user_id in self.residents:
            raise ValueError("Duplicate resident")
        status = Status.UNAVAILABLE if saved is None else Status(saved["confirmed"])
        self.residents[user_id] = Resident(user_id, name, device_id, tracker, confirmed=status)

    def overall(self) -> Status:
        states = [r.confirmed for r in self.residents.values()]
        if any(s is Status.HOME for s in states):
            return Status.HOME
        if states and all(s is Status.NOT_HOME for s in states):
            return Status.NOT_HOME
        return Status.UNAVAILABLE

    def _decide(self, r: Resident, now: datetime) -> Status | None:
        gps = r.gps if r.last_gps_at and timedelta(0) <= now-r.last_gps_at <= timedelta(seconds=self.freshness_seconds) else Status.UNAVAILABLE
        wifi = r.wifi if r.last_wifi_at and timedelta(0) <= now-r.last_wifi_at <= timedelta(seconds=self.freshness_seconds) else Status.UNAVAILABLE
        if self.mode is Mode.GPS:
            return gps if gps is not Status.UNAVAILABLE else None
        if self.mode is Mode.WIFI:
            return wifi if wifi is not Status.UNAVAILABLE else None
        if wifi is Status.HOME:
            return Status.HOME
        if (wifi is Status.NOT_HOME and r.wifi_absent_since is not None
                and now-r.wifi_absent_since >= timedelta(minutes=self.wifi_absence_minutes)
                and r.confirmed is Status.HOME):
            return Status.NOT_HOME
        return gps if gps is not Status.UNAVAILABLE else None

    def _change(self, r: Resident, when: datetime, events: list[dict]):
        outcome = self._decide(r, when)
        if outcome is None or outcome is r.confirmed:
            r.initialized = True
            return
        before = r.confirmed
        r.confirmed = outcome
        if r.initialized and before is not Status.UNAVAILABLE:
            events.append({"event_type": "arrival" if outcome is Status.HOME else "departure", "resident_id": r.key, "source": self.mode.value, "observed_at": when.isoformat()})
        r.initialized = True

    def gps_observation(self, user_id: str, value: Status, when: datetime, distance: float | None = None) -> list[dict]:
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("Timezone required")
        r = self.residents[user_id]
        value = Status(value)
        if r.last_gps_at is not None and when < r.last_gps_at:
            return []
        before = r.gps
        r.gps = value
        r.last_gps_at = when if value is not Status.UNAVAILABLE else r.last_gps_at
        r.distance = distance if value is not Status.UNAVAILABLE else None
        events = []
        if r.initialized and before in (Status.HOME, Status.NOT_HOME) and value in (Status.HOME, Status.NOT_HOME) and before is not value:
            events.append({"event_type": "gps_in" if value is Status.HOME else "gps_out", "resident_id": r.key, "source": "gps", "observed_at": when.isoformat()})
        if value is not Status.UNAVAILABLE:
            self._change(r, when, events)
        return events

    def wifi_observation(self, user_id: str, value: Status, when: datetime, *, verified: bool) -> list[dict]:
        """Only verified network evidence may change state. Never call NOT_HOME for ARP timeout."""
        value = Status(value)
        if value is not Status.UNAVAILABLE and not verified:
            raise ValueError("Wi-Fi evidence not verified")
        r = self.residents[user_id]
        if r.last_wifi_at and when < r.last_wifi_at:
            return []
        before = r.wifi
        events = []
        if value is Status.UNAVAILABLE:
            r.wifi = Status.UNAVAILABLE
            r.wifi_absent_since = None
        else:
            gap = (when-r.last_wifi_at).total_seconds() if r.last_wifi_at else None
            if value is Status.NOT_HOME:
                if before is not Status.NOT_HOME or gap is None or gap > self.freshness_seconds:
                    r.wifi_absent_since = when
            else:
                r.wifi_absent_since = None
            r.wifi = value
            r.last_wifi_at = when
            if r.initialized and before in (Status.HOME, Status.NOT_HOME) and before is not value:
                events.append({"event_type": "wifi_in" if value is Status.HOME else "wifi_out", "resident_id": r.key, "source": "wifi", "observed_at": when.isoformat()})
            self._change(r, when, events)
        return events

    def expire(self, now: datetime):
        for r in self.residents.values():
            if r.last_gps_at is None or now-r.last_gps_at > timedelta(seconds=self.freshness_seconds):
                r.gps = Status.UNAVAILABLE
                r.distance = None
            if r.last_wifi_at is None or now-r.last_wifi_at > timedelta(seconds=self.freshness_seconds):
                r.wifi = Status.UNAVAILABLE
                r.wifi_absent_since = None
        # No transitions on source expiration.

    def persistent(self) -> dict:
        return {"schema_version": 1, "residents": [
            {"user_id": r.user_id, "confirmed": r.confirmed.value}
            for r in self.residents.values()]}

    def snapshot(self) -> dict:
        return {"mode": self.mode.value, "status": self.overall().value,
                "residents_total": len(self.residents),
                "residents_home": sum(r.confirmed is Status.HOME for r in self.residents.values()),
                "residents": {r.key: {"name": r.name, "status": r.confirmed.value,
                                      "gps": r.gps.value, "wifi": r.wifi.value}
                              for r in self.residents.values()}}
