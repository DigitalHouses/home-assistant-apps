"""Pure, per-network infrastructure FSM. No Zigbee control or Home Assistant logic."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping


STATES = ("BOOTING", "HEALTHY", "DEGRADED", "CRITICAL")
PRIORITY = {"HEALTHY": 0, "BOOTING": 1, "DEGRADED": 2, "CRITICAL": 3}


def auto_threshold(baseline: float | None) -> int | None:
    """AUTO uses floor(50% of baseline); zero disables only the RPM alarm."""
    if baseline is None:
        return None
    if not math.isfinite(baseline) or baseline < 0:
        raise ValueError("baseline must be a finite nonnegative number")
    return math.floor(baseline / 2)


def rpm_below_threshold(rpm: float | None, threshold: int | None) -> bool:
    """10% tolerance: trigger only below 90% of positive effective threshold."""
    return (rpm is not None and threshold is not None and
            threshold > 0 and rpm < threshold * 0.9)


def aggregate_fsm(states: list[str]) -> str:
    """Worst confirmed infrastructure state; UNKNOWN is not an FSM value."""
    if any(state not in PRIORITY for state in states):
        raise ValueError("invalid network FSM state")
    return max(states, key=PRIORITY.__getitem__) if states else "BOOTING"


@dataclass
class NetworkFSM:
    """Transitions are immediate; MPM and observer loss escalate after five minutes.

    A confirmed repeater failure requires 60 continuous seconds offline.
    BOOTING exists only until the first usable bridge/inventory snapshot.
    """
    state: str = "BOOTING"
    reason: str = "initial_sync"
    initialized: bool = False
    boot_completed_at: float | None = None
    low_since: float | None = None
    missing_since: float | None = None
    repeater_offline_since: dict[str, float] = field(default_factory=dict)

    def observe(
        self, *, now: float, bridge_state: str, inventory_observed: bool,
        rpm: float | None, threshold: int | None,
        repeaters: Mapping[str, str] | None = None,
    ) -> tuple[str, str]:
        if bridge_state == "offline":
            self.low_since = None
            self.missing_since = None
            self.repeater_offline_since.clear()
            self.state, self.reason = "CRITICAL", "bridge_offline"
            return self.state, self.reason

        if bridge_state != "online" or not inventory_observed:
            self.low_since = None
            self.repeater_offline_since.clear()
            if not self.initialized:
                self.state, self.reason = "BOOTING", "initial_sync"
                return self.state, self.reason
            if self.missing_since is None:
                self.missing_since = now
            elapsed = max(0.0, now - self.missing_since)
            self.state = "CRITICAL" if elapsed >= 300 else "DEGRADED"
            self.reason = "observation_lost"
            return self.state, self.reason

        self.missing_since = None
        if not self.initialized:
            self.initialized = True
            self.boot_completed_at = now

        if (rpm is not None and
                (not math.isfinite(rpm) or rpm < 0)):
            raise ValueError("RPM must be a finite nonnegative number")
        if threshold is not None and (type(threshold) is not int or threshold < 0):
            raise ValueError("threshold must be a nonnegative integer")

        # A confirmed *zero* threshold explicitly disables the traffic
        # detector. Quiet battery-only networks must remain HEALTHY even after
        # hours without messages. Clear any previous RPM fault/timer immediately
        # when AUTO computes 0 or the user selects MANUAL 0. Bridge/observer
        # and repeater checks remain independent of MQTT traffic.
        if threshold == 0:
            self.low_since = None
            rpm_degraded = False
        elif rpm_below_threshold(rpm, threshold):
            if self.low_since is None:
                self.low_since = now
            low_for = max(0.0, now - self.low_since)
            if low_for >= 300:
                self.state, self.reason = "CRITICAL", "rpm_low_5m"
                return self.state, self.reason
            rpm_degraded = True
        else:
            self.low_since = None
            rpm_degraded = False

        confirmed_repeaters = False
        current = repeaters or {}
        for ieee in list(self.repeater_offline_since):
            if current.get(ieee) != "offline":
                self.repeater_offline_since.pop(ieee, None)
        for ieee, status in current.items():
            if status == "offline":
                self.repeater_offline_since.setdefault(ieee, now)
                if now - self.repeater_offline_since[ieee] >= 60:
                    confirmed_repeaters = True

        if confirmed_repeaters:
            self.state, self.reason = "DEGRADED", "repeater_offline"
        elif rpm_degraded:
            self.state, self.reason = "DEGRADED", "rpm_below_threshold"
        else:
            self.state, self.reason = "HEALTHY", "ok"
        return self.state, self.reason
