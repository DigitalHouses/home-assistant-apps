"""Independent per-network problem decisions, separate from MQTT publication.

Only confirmed failures are ON. Incomplete input yields None/unavailable.
The traffic detector confirms sustained low RPM, not a broken coordinator.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

PROBLEM_TYPES = ("bridge_offline", "devices_offline", "mqtt_traffic_low")


@dataclass(frozen=True)
class Problem:
    network_id: str
    kind: str
    active: bool | None
    severity: str
    object_name: str
    metric: str
    value: int | float | None = None
    average: float | None = None
    threshold: int | float | None = None

    @property
    def problem_id(self) -> str:
        return f"{self.network_id}:{self.kind}"

    def presentation(self) -> dict[str, object]:
        return {
            "problem_id": self.problem_id,
            "network_id": self.network_id,
            "category": self.kind,
            "severity": self.severity,
            "object_id": self.network_id,
            "object_name": self.object_name,
            "metric": self.metric,
            "value": self.value,
            "average": self.average,
            "threshold": self.threshold,
        }


class TrafficDetector:
    """Per-network time-based hysteresis; no transitions from invalid metrics."""

    def __init__(self, *, confirm_seconds: int = 300,
                 recover_seconds: int = 120) -> None:
        self.confirm_seconds = confirm_seconds
        self.recover_seconds = recover_seconds
        self.current: bool | None = None
        self.low_since: float | None = None
        self.normal_since: float | None = None

    def reset(self) -> None:
        self.current = None
        self.low_since = None
        self.normal_since = None

    def observe(self, *, now: float, rpm: float | None,
                threshold: float | None) -> bool | None:
        if (rpm is None or threshold is None or not math.isfinite(rpm)
                or not math.isfinite(threshold) or rpm < 0 or threshold <= 0):
            self.reset()
            return None
        if rpm < threshold:
            self.normal_since = None
            if self.low_since is None:
                self.low_since = now
            if now - self.low_since >= self.confirm_seconds:
                self.current = True
            return self.current
        # Recovery hysteresis prevents brief bursts from masking a real stall.
        self.low_since = None
        if self.current is not True:
            self.current = False
            self.normal_since = None
        elif rpm >= threshold * 1.3:
            if self.normal_since is None:
                self.normal_since = now
            if now - self.normal_since >= self.recover_seconds:
                self.current = False
                self.normal_since = None
        else:
            self.normal_since = None
        return self.current


def network_problems(*, network_id: str, name: str, bridge_state: str,
                     inventory_observed: bool, devices: int,
                     offline: int, unknown: int,
                     rpm_problem: bool | None, rpm: float | None,
                     threshold: float | None) -> tuple[Problem, ...]:
    bridge = True if bridge_state == "offline" else (
        False if bridge_state == "online" else None
    )
    device_problem = None
    if bridge_state == "online" and inventory_observed:
        if offline > 0:
            device_problem = True
        elif unknown == 0:
            device_problem = False
    return (
        Problem(network_id, "bridge_offline", bridge, "critical", name,
                "bridge_state", value=None),
        Problem(network_id, "devices_offline", device_problem, "warning", name,
                "offline_devices", value=offline if device_problem is not None else None),
        Problem(network_id, "mqtt_traffic_low", rpm_problem, "warning", name,
                "messages_per_minute", value=rpm, average=rpm, threshold=threshold),
    )
