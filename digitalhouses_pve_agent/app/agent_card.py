"""Compact Home Assistant agent card: app-owned operation and collection state.

Only accepted user commands occupy the foreground. Background collection and
scheduled release checks update data freshness without stealing the card.
"""
from __future__ import annotations

import time
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .state_store import StateStore

RESULT_SECONDS = 5.0
COLLECTION_PUBLISH_SECONDS = 30.0
OPERATIONS = frozenset({"refresh", "check", "install", "restart"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def linux_boot_id() -> str | None:
    """The monotonic clock is comparable across processes on the same Linux boot."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip() or None
    except OSError:
        return None


class AgentCard:
    def __init__(
        self, path: Path, publisher: Callable[[dict[str, object]], bool],
        *, clock: Callable[[], float] = time.monotonic,
        now: Callable[[], str] = utc_now,
        boot_id: Callable[[], str | None] = linux_boot_id,
    ) -> None:
        self.store = StateStore(path)
        self.publisher = publisher
        self.clock = clock
        self.now = now
        self._boot_id = boot_id()
        self._start_boot_id: str | None = None
        self._started_monotonic: float | None = None
        self._result_monotonic: float | None = None
        self._last_collection_publish: float | None = None
        try:
            saved = self.store.load()
        except Exception:
            saved = {}
        self.last_collection_at = saved.get("last_collection_at")
        self.operation = saved.get("operation") if saved.get("operation") in OPERATIONS else None
        self.state = saved.get("state") if saved.get("state") in {"running", "success", "error"} else "idle"
        self.started_at = saved.get("started_at")
        self.finished_at = saved.get("finished_at")
        self.duration_seconds = saved.get("duration_seconds")
        self.error = saved.get("error")
        if self.state == "running" and self.operation in {"restart", "install"}:
            persisted_boot = saved.get("_start_boot_id")
            persisted_mono = saved.get("_started_monotonic")
            # Reuse CLOCK_MONOTONIC across service restarts, but never
            # across a reboot or with an untrusted/legacy state file.
            if (
                isinstance(persisted_boot, str)
                and persisted_boot
                and persisted_boot == self._boot_id
                and isinstance(persisted_mono, (int, float))
                and not isinstance(persisted_mono, bool)
                and math.isfinite(persisted_mono)
                and 0 <= persisted_mono <= self.clock()
            ):
                self._started_monotonic = float(persisted_mono)
                self._start_boot_id = persisted_boot
        if self.state == "running" and self.operation not in {"restart", "install"}:
            # Only a service restart and an external update worker can survive
            # this Python process. Anything else was interrupted.
            self.state = "error"
            self.finished_at = self.now()
            self.error = "Операция прервана перезапуском агента"
            self.duration_seconds = self._elapsed_wall()
        elif self.state == "success":
            # Completed-state visibility is transient, not replayed on restart.
            self.state = "idle"
            self.operation = None
        self._persist()

    def _elapsed_wall(self) -> float | None:
        try:
            start = datetime.fromisoformat(str(self.started_at))
            end = datetime.fromisoformat(self.now())
            return round(max(0.0, (end - start).total_seconds()), 3)
        except (TypeError, ValueError):
            return None

    def _persist(self) -> None:
        state = self.payload()
        # Internal-only checkpoint. Do not expose clock origins over MQTT.
        state["_started_monotonic"] = self._started_monotonic
        state["_start_boot_id"] = self._start_boot_id
        self.store.save(state)

    def payload(self) -> dict[str, object]:
        return {
            "state": self.state,
            "operation": self.operation,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "last_collection_at": self.last_collection_at,
        }

    def publish(self) -> bool:
        return bool(self.publisher(self.payload()))

    def begin(self, operation: str) -> bool:
        if operation not in OPERATIONS:
            raise ValueError(f"Unsupported operation: {operation}")
        if self.state == "running":
            return False
        self.operation = operation
        self.state = "running"
        self.started_at = self.now()
        self.finished_at = None
        self.duration_seconds = None
        self.error = None
        self._started_monotonic = self.clock()
        self._start_boot_id = self._boot_id
        self._result_monotonic = None
        self._persist()
        self.publish()
        return True

    def finish(
        self, operation: str, *, error: str | None = None,
        measured_seconds: float | None = None,
    ) -> bool:
        if self.state != "running" or self.operation != operation:
            return False
        if measured_seconds is not None:
            self.duration_seconds = round(max(0.0, measured_seconds), 3)
        elif self._started_monotonic is not None:
            elapsed = max(0.0, self.clock() - self._started_monotonic)
            self.duration_seconds = round(elapsed, 3)
        else:
            self.duration_seconds = self._elapsed_wall()
        self.finished_at = self.now()
        self.state = "error" if error else "success"
        self.error = error
        self._result_monotonic = self.clock() if not error else None
        self._started_monotonic = None
        self._start_boot_id = None
        self._persist()
        self.publish()
        return True

    def collected(self, timestamp: str) -> None:
        self.last_collection_at = timestamp
        now = self.clock()
        if (self._last_collection_publish is None or
                now - self._last_collection_publish >= COLLECTION_PUBLISH_SECONDS):
            self._last_collection_publish = now
            self._persist()
            self.publish()

    def tick(self) -> None:
        if self.state != "success":
            return
        if self._result_monotonic is None:
            return
        if self.clock() - self._result_monotonic < RESULT_SECONDS:
            return
        self.state = "idle"
        self.operation = None
        self.started_at = None
        self.finished_at = None
        self.duration_seconds = None
        self.error = None
        self._result_monotonic = None
        self._persist()
        self.publish()
