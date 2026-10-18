"""Pure presence engine. Each resident is identified by one explicitly selected GPS tracker."""
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


def resident_key(tracker: str) -> str:
    validate_tracker(tracker)
    return hashlib.sha256(tracker.encode("utf-8")).hexdigest()[:16]


def validate_tracker(tracker: str) -> str:
    if not isinstance(tracker, str) or not tracker.startswith("device_tracker.") or len(tracker) <= len("device_tracker.") or tracker != tracker.strip():
        raise ValueError("One valid device_tracker entity ID is required per resident")
    return tracker


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
    tracker: str
    name: str
    user_name: str | None = None
    confirmed: Status = Status.UNAVAILABLE
    gps: Status = Status.UNAVAILABLE
    wifi: Status = Status.UNAVAILABLE
    wifi_source: str = "legacy"  # Runtime router-tracker source bypasses probe freshness
    wifi_tracker_id: str | None = None
    last_gps_at: datetime | None = None
    last_wifi_at: datetime | None = None
    wifi_absent_since: datetime | None = None
    confirmed_changed_at: datetime | None = None
    gps_changed_at: datetime | None = None
    wifi_changed_at: datetime | None = None
    wifi_last_probe_at: datetime | None = None
    wifi_probe_result: str = "not_checked"
    # Last decision backed by a real MAC reply or a fully debounced no-reply
    # sequence. Technical UNAVAILABLE never changes notification history.
    wifi_last_decisive: Status = Status.UNAVAILABLE
    wifi_method_baseline_pending: bool = False
    wifi_monitor_initialized: bool = False
    distance: float | None = None
    initialized: bool = False

    @property
    def key(self) -> str:
        return resident_key(self.tracker)


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

    def add(self, tracker: str, name: str, saved: dict | None = None,
            user_name: str | None = None):
        validate_tracker(tracker)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Resident device name cannot be blank")
        if user_name is not None and (not isinstance(user_name, str) or not user_name.strip()):
            raise ValueError("Resident user name cannot be blank")
        if tracker in self.residents:
            raise ValueError("Duplicate device_tracker")
        status = Status.UNAVAILABLE if saved is None else Status(saved["confirmed"])
        self.residents[tracker] = Resident(
            tracker, name.strip(), user_name=user_name.strip() if user_name else None,
            confirmed=status,
            confirmed_changed_at=(datetime.fromisoformat(saved["confirmed_changed_at"])
                if saved and saved.get("confirmed_changed_at") else None),
        )

    def overall(self) -> Status:
        states = [r.confirmed for r in self.residents.values()]
        if any(s is Status.HOME for s in states):
            return Status.HOME
        if states and all(s is Status.NOT_HOME for s in states):
            return Status.NOT_HOME
        return Status.UNAVAILABLE

    def set_mode(self, mode: Mode):
        """Set live decision mode without inventing a source observation or event."""
        self.mode = Mode(mode)

    def _decide(self, r: Resident, now: datetime) -> Status | None:
        # A phone may remain still for days. An old, valid HA GPS report is
        # the last known position, not a failed observation. Wi-Fi evidence
        # still requires independently verified, fresh observations.
        gps = r.gps if r.last_gps_at and now >= r.last_gps_at else Status.UNAVAILABLE
        # Router trackers are polled from current HA states every runtime loop.
        # The old PING/ARP freshness threshold must not erase router HOME.
        wifi = (r.wifi if r.wifi_source == "router" else
                Status.NOT_HOME if r.wifi is Status.NOT_HOME else
                r.wifi if r.wifi is Status.HOME and r.last_wifi_at
                    and timedelta(0) <= now-r.last_wifi_at <= timedelta(minutes=self.wifi_absence_minutes + 2)
                else Status.UNAVAILABLE)
        if self.mode is Mode.GPS:
            return gps if gps is not Status.UNAVAILABLE else None
        if self.mode is Mode.WIFI:
            return wifi if wifi is not Status.UNAVAILABLE else None
        if wifi in (Status.HOME, Status.NOT_HOME):
            # Hybrid uses completed, debounced ARP absence even if iOS GPS
            # still says HOME. Infrastructure errors never produce NOT_HOME.
            return wifi
        return gps if gps is not Status.UNAVAILABLE else None

    def _change(self, r: Resident, when: datetime, events: list[dict]):
        outcome = self._decide(r, when)
        if outcome is None or outcome is r.confirmed:
            r.initialized = True
            return
        before = r.confirmed
        before_home = self.overall()
        r.confirmed = outcome
        r.confirmed_changed_at = when
        after_home = self.overall()
        if r.initialized and before is not Status.UNAVAILABLE:
            events.append({
                "event_type": "arrival" if outcome is Status.HOME else "departure",
                "resident_id": r.key,
                "source": self.mode.value,
                "observed_at": when.isoformat(),
                "first_arrival": before_home is Status.NOT_HOME and after_home is Status.HOME,
                "last_departure": before_home is Status.HOME and after_home is Status.NOT_HOME,
                "residents_home_after": sum(x.confirmed is Status.HOME for x in self.residents.values()),
            })
        r.initialized = True

    def gps_observation(self, tracker: str, value: Status, when: datetime, distance: float | None = None,
                        *, decision_at: datetime | None = None) -> list[dict]:
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("Timezone required")
        r = self.residents[tracker]
        value = Status(value)
        if r.last_gps_at is not None and when < r.last_gps_at:
            return []
        # HA returns the same last-known iOS GPS observation on every poll.
        # A repeated report is not new evidence and must not undo a newer
        # Wi-Fi HOME decision after the Wi-Fi source becomes uncertain.
        repeated = (r.initialized and r.last_gps_at == when and r.gps is value)
        before = r.gps
        r.gps = value
        if value is not Status.UNAVAILABLE and value is not before:
            r.gps_changed_at = when
        r.last_gps_at = when if value is not Status.UNAVAILABLE else r.last_gps_at
        r.distance = distance if value is not Status.UNAVAILABLE else None
        if repeated:
            return []  # No synthetic presence events from repeated old GPS.
        events = []
        if r.initialized and before in (Status.HOME, Status.NOT_HOME) and value in (Status.HOME, Status.NOT_HOME) and before is not value:
            events.append({"event_type": "gps_in" if value is Status.HOME else "gps_out", "resident_id": r.key, "source": "gps", "observed_at": when.isoformat()})
        if value is not Status.UNAVAILABLE:
            # The GPS source can be days old for a stationary iPhone.
            # Evaluate Wi-Fi evidence against current wall time, never against
            # that old GPS observation timestamp.
            self._change(r, decision_at or when, events)
        return events

    def reset_wifi_methods(self, when: datetime, *, disabled: bool = False) -> None:
        """Changing household probe methods starts a fresh baseline, no synthetic events.

        In Wi-Fi-only mode, disabling all methods must yield unknown, never the
        previously confirmed presence. Hybrid falls back to existing GPS evidence.
        """
        for r in self.residents.values():
            if r.wifi is not Status.UNAVAILABLE:
                r.wifi_changed_at = when
            r.wifi = Status.UNAVAILABLE
            r.wifi_absent_since = None
            r.last_wifi_at = None
            r.wifi_last_probe_at = None
            r.wifi_last_decisive = Status.UNAVAILABLE
            r.wifi_monitor_initialized = False
            r.wifi_method_baseline_pending = True
            r.wifi_probe_result = "disabled" if disabled else "reconfiguring"
            if self.mode is not Mode.GPS:
                fallback = self._decide(r, when)
                status = fallback if fallback is not None else Status.UNAVAILABLE
                if r.confirmed is not status:
                    r.confirmed = status
                    r.confirmed_changed_at = when
                r.initialized = False

    def wifi_observation(self, tracker: str, value: Status, when: datetime, *, verified: bool) -> list[dict]:
        """Only independently verified evidence may affect Wi-Fi. No ARP timeout as absence."""
        value = Status(value)
        if value is not Status.UNAVAILABLE and not verified:
            raise ValueError("Wi-Fi evidence not verified")
        r = self.residents[tracker]
        if r.last_wifi_at and when < r.last_wifi_at:
            return []
        before = r.wifi
        prior_decisive = r.wifi_last_decisive
        events = []
        if value is Status.UNAVAILABLE:
            r.wifi = Status.UNAVAILABLE
            r.wifi_absent_since = None
            if before is not Status.UNAVAILABLE:
                r.wifi_changed_at = when
        else:
            gap = (when-r.last_wifi_at).total_seconds() if r.last_wifi_at else None
            if value is Status.NOT_HOME:
                if before is not Status.NOT_HOME or gap is None or gap > self.freshness_seconds:
                    r.wifi_absent_since = when
            else:
                r.wifi_absent_since = None
            r.wifi = value
            r.last_wifi_at = when if value is Status.HOME else r.last_wifi_at
            if before is not value:
                r.wifi_changed_at = when
            # A temporary UNAVAILABLE (probe error or expired evidence)
            # is not a real departure. Compare the latest decisive evidence,
            # not the current diagnostic sensor state, to avoid duplicate
            # wifi_in when ARP replies resume after an unknown interval.
            if (r.wifi_monitor_initialized and not r.wifi_method_baseline_pending
                    and prior_decisive is not value
                    and (value is Status.HOME or prior_decisive is Status.HOME)):
                events.append({
                    "event_type": "wifi_in" if value is Status.HOME else "wifi_out",
                    "resident_id": r.key, "source": "wifi",
                    "observed_at": when.isoformat(),
                })
            r.wifi_last_decisive = value
            r.wifi_method_baseline_pending = False
            self._change(r, when, events)
        return events

    def wifi_no_reply(self, tracker: str, when: datetime) -> list[dict]:
        """A completed on-link ARP probe returned no matching phone reply.

        Require 15 minutes of consecutive successful negative probes. Technical
        probe failures reset this sequence; they never become NOT_HOME.
        """
        r = self.residents[tracker]
        if (r.wifi_absent_since is None or
                (r.wifi_last_probe_at is not None
                 and (when-r.wifi_last_probe_at).total_seconds() > 150)):
            r.wifi_absent_since = when
        if when-r.wifi_absent_since < timedelta(minutes=self.wifi_absence_minutes):
            return []
        if r.wifi is Status.NOT_HOME:
            return []
        prior_decisive = r.wifi_last_decisive
        r.wifi = Status.NOT_HOME
        r.wifi_changed_at = when
        events = []
        if r.wifi_monitor_initialized and not r.wifi_method_baseline_pending and prior_decisive is Status.HOME:
            events.append({"event_type": "wifi_out", "resident_id": r.key,
                           "source": "wifi", "observed_at": when.isoformat(),
                           "timeout_minutes": self.wifi_absence_minutes})
        r.wifi_last_decisive = Status.NOT_HOME
        r.wifi_method_baseline_pending = False
        self._change(r, when, events)
        return events

    def wifi_probe_failed(self, tracker: str, when: datetime):
        """No validated observation. Mark only the source as unknown."""
        r = self.residents[tracker]
        if r.wifi is not Status.UNAVAILABLE:
            r.wifi_changed_at = when
        r.wifi = Status.UNAVAILABLE
        r.wifi_absent_since = None

    def expire(self, now: datetime) -> list[dict]:
        events = []
        for r in self.residents.values():
            # iOS may sleep without replying to ARP. Loss of positive Wi-Fi
            # evidence after the grace period is NOT verified disconnection.
            if (r.wifi_absent_since is None
                    and (r.last_wifi_at is None
                         or now-r.last_wifi_at >= timedelta(minutes=self.wifi_absence_minutes))):
                if (r.wifi is Status.HOME and r.wifi_monitor_initialized
                        and r.last_wifi_at is not None):
                    events.append({
                        "event_type": "wifi_lost",
                        "resident_id": r.key,
                        "source": "wifi",
                        "observed_at": now.isoformat(),
                        "last_verified_at": r.last_wifi_at.isoformat(),
                        "timeout_minutes": self.wifi_absence_minutes,
                    })
                if r.wifi is not Status.UNAVAILABLE:
                    r.wifi_changed_at = now
                r.wifi = Status.UNAVAILABLE
        return events

    def persistent(self) -> dict:
        return {"schema_version": 2, "residents": [
            {"tracker": r.tracker, "confirmed": r.confirmed.value,
             "confirmed_changed_at": r.confirmed_changed_at.isoformat()
                 if r.confirmed_changed_at else None}
            for r in self.residents.values()]}

    def snapshot(self) -> dict:
        # Wi-Fi-only never inherits a retained GPS state. The positive-only
        # pilot can prove Wi-Fi HOME, but cannot prove Wi-Fi NOT_HOME merely
        # because a sleeping iPhone fails to answer ARP.
        states = [r.wifi if self.mode is Mode.WIFI else r.confirmed
                  for r in self.residents.values()]
        status = (Status.HOME if Status.HOME in states
                  else Status.NOT_HOME if states and all(v is Status.NOT_HOME for v in states)
                  else Status.UNAVAILABLE)
        residents_home = sum(v is Status.HOME for v in states)
        return {"mode": self.mode.value, "status": status.value,
                "residents_total": len(self.residents), "gps_freshness_seconds": self.freshness_seconds,
                "residents_home": residents_home,
                "residents": {r.key: {"name": r.name,
                                      "user_name": r.user_name,
                                      "gps_tracker": r.tracker,
                                      "wifi_tracker": r.wifi_tracker_id,
                                      "status": (r.wifi.value if self.mode is Mode.WIFI else r.confirmed.value),
                                      "status_changed_at": ((r.wifi_changed_at if self.mode is Mode.WIFI
                                          else r.confirmed_changed_at).isoformat()
                                          if (r.wifi_changed_at if self.mode is Mode.WIFI
                                          else r.confirmed_changed_at) else None),
                                      "gps": r.gps.value,
                                      "gps_changed_at": r.gps_changed_at.isoformat() if r.gps_changed_at else None,
                                      "gps_reported_at": r.last_gps_at.isoformat() if r.last_gps_at else None,
                                      "wifi": r.wifi.value,
                                      "wifi_source": r.wifi_source,
                                      "wifi_changed_at": r.wifi_changed_at.isoformat() if r.wifi_changed_at else None,
                                      "wifi_no_reply_since": r.wifi_absent_since.isoformat() if r.wifi_absent_since else None,
                                      "wifi_last_verified_at": r.last_wifi_at.isoformat() if r.last_wifi_at else None,
                                      "wifi_last_probe_at": r.wifi_last_probe_at.isoformat() if r.wifi_last_probe_at else None,
                                      "wifi_probe_result": r.wifi_probe_result}
                              for r in self.residents.values()}}
