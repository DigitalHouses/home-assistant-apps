"""Transition-only, durable GPU/driver notifications for HA MQTT event entities.

The authoritative health data is supplied by gpu_collector + sysfs.  This
module never diagnoses GPU activity from Plex transcoder processes.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .state_store import StateStore, StateStoreError

GPU_EVENT_TYPES = (
    "gpu_unavailable",
    "gpu_restored",
    "gpu_driver_unbound",
    "gpu_driver_restored",
    "gpu_driver_changed",
)
DEFAULT_GPU_EVENT_STATE = Path("/var/lib/digitalhouses_plex_agent/gpu_events.json")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classification(payload: Mapping[str, object]) -> dict[str, object] | None:
    """Separate a bound kernel driver from operational GPU hardware."""
    supported = payload.get("supported")
    if not isinstance(supported, bool):
        return None
    pci = payload.get("pci_address")
    driver = payload.get("driver_status")
    driver_name = payload.get("driver_name")
    if supported is False:
        return {"health": "absent", "driver": "not_detected",
                "driver_name": None, "pci_address": None, "status": "unsupported"}
    if driver not in {"bound", "not_bound"}:
        return None
    status = payload.get("status")
    if status in {"starting", "unknown", "unsupported", None}:
        return None
    if driver == "not_bound":
        health = "fault"
    elif status == "ok" and payload.get("available") is True:
        health = "ok"
    elif status in {"error", "stale", "tool_missing", "helper_unavailable",
                    "helper_error"}:
        health = "fault"
    else:
        return None
    return {
        "health": health,
        "driver": driver,
        "driver_name": str(driver_name) if driver == "bound" and driver_name else None,
        "pci_address": str(pci) if pci else None,
        "status": str(status),
    }


def _transition(previous: Mapping[str, object] | None,
                current: Mapping[str, object]) -> str | None:
    driver = current["driver"]
    old_driver = previous.get("driver") if previous else None
    old_health = previous.get("health") if previous else None
    health = current["health"]

    # Driver changes take precedence, so a single failure does not generate
    # both a driver alert and a GPU alert for the same observation.
    if driver == "not_bound" and old_driver != "not_bound":
        return "gpu_driver_unbound"
    if old_driver == "not_bound" and driver == "bound":
        return "gpu_driver_restored"
    if (old_driver == driver == "bound" and previous is not None
            and previous.get("driver_name") != current.get("driver_name")):
        return "gpu_driver_changed"
    if health == "fault" and old_health not in {"fault", "absent"}:
        return "gpu_unavailable"
    if health == "absent" and old_health in {"ok", "fault"}:
        return "gpu_unavailable" if old_health == "ok" else None
    if health == "ok" and old_health in {"fault", "absent"}:
        return "gpu_restored"
    return None


def _event(event_type: str, previous: Mapping[str, object] | None,
           current: Mapping[str, object], observed_at: str) -> dict[str, object]:
    is_recovery = event_type in {"gpu_restored", "gpu_driver_restored"}
    return {
        "schema_version": 2,
        "event_id": str(uuid4()),
        "event_type": event_type,
        "observed_at": observed_at,
        "category": "gpu",
        "severity": "info" if is_recovery else "warning",
        "object_id": current.get("pci_address") or (previous or {}).get("pci_address") or "intel_gpu",
        "object_name": "Intel GPU",
        "problem_id": "gpu_driver" if event_type.startswith("gpu_driver_") else "gpu_health",
        "previous": dict(previous) if previous else None,
        "current": dict(current),
        "gpu_status": current.get("status"),
        "gpu_available": current.get("health") == "ok",
        "driver_status": current.get("driver"),
        "driver_name": current.get("driver_name"),
        "pci_address": current.get("pci_address"),
    }


class GpuEventTracker:
    """Two-sample stable transitions; persist previous confirmed state/outbox.

    Publish is non-retained QoS 1. MQTT rc success only acknowledges local queueing,
    not Home Assistant's consumption. On reconnect, already queued events are not
    replayed; failed publishes remain on disk for the next attempt.
    """

    def __init__(
        self, path: Path = DEFAULT_GPU_EVENT_STATE, *,
        now: Callable[[], str] = _iso_now,
        confirmations: int = 2,
    ) -> None:
        self.store = StateStore(path)
        self.log = logging.getLogger(__name__)
        self.now = now
        self.confirmations = max(2, int(confirmations))
        try:
            saved = self.store.load()
        except StateStoreError:
            self.log.warning("Invalid saved GPU event state; resetting", exc_info=True)
            saved = {}
        confirmed = saved.get("confirmed")
        self.confirmed: dict[str, object] | None = (
            dict(confirmed) if isinstance(confirmed, dict) else None
        )
        pending = saved.get("outbox")
        self.outbox: list[dict[str, object]] = (
            [dict(x) for x in pending if isinstance(x, dict)]
            if isinstance(pending, list) else []
        )
        self._candidate: dict[str, object] | None = None
        self._candidate_count = 0

    def _save(self) -> None:
        self.store.save({"confirmed": self.confirmed, "outbox": self.outbox})

    def observe(self, payload: Mapping[str, object]) -> str | None:
        current = _classification(payload)
        if current is None:
            self._candidate = None
            self._candidate_count = 0
            return None
        # Ignore changing sampling/diagnostic timestamps and raw percentages;
        # only semantic conditions qualify as an event.
        if current == self.confirmed:
            self._candidate = None
            self._candidate_count = 0
            return None
        if self._candidate == current:
            self._candidate_count += 1
        else:
            self._candidate = current
            self._candidate_count = 1
        if self._candidate_count < self.confirmations:
            return None
        previous = self.confirmed
        self.confirmed = current
        self._candidate = None
        self._candidate_count = 0
        event_type = _transition(previous, current)
        if event_type:
            self.outbox.append(_event(event_type, previous, current, self.now()))
        self._save()
        return event_type

    def flush(self, publisher: Callable[[dict[str, object]], bool]) -> int:
        sent = 0
        while self.outbox:
            if not publisher(self.outbox[0]):
                break
            self.outbox.pop(0)
            self._save()
            sent += 1
        return sent
