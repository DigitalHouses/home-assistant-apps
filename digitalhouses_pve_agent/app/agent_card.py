"""Compact Home Assistant agent card: app-owned operation and collection state.

Only accepted user commands occupy the foreground. Background collection and
scheduled release checks update data freshness without stealing the card.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable


RESULT_SECONDS = 5.0
COLLECTION_PUBLISH_SECONDS = 30.0
OPERATIONS = frozenset({"refresh", "check", "install", "restart"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentCard:
    """Transient presentation of current runtime operations; no disk checkpoint."""

    def __init__(
        self, publisher: Callable[[dict[str, object]], bool],
        *, clock: Callable[[], float] = time.monotonic,
        now: Callable[[], str] = utc_now,
    ) -> None:
        self.publisher = publisher
        self.clock = clock
        self.now = now
        self._started_monotonic: float | None = None
        self._result_monotonic: float | None = None
        self._last_collection_publish: float | None = None
        self.last_collection_at: str | None = None
        self.operation: str | None = None
        self.state = "idle"
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.duration_seconds: float | None = None
        self.error: str | None = None

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

    def begin(self, operation: str, *, observed: bool = False) -> bool:
        if operation not in OPERATIONS:
            raise ValueError(f"Unsupported operation: {operation}")
        if self.state == "running":
            return False
        self.operation = operation
        self.state = "running"
        self.started_at = None if observed else self.now()
        self.finished_at = None
        self.duration_seconds = None
        self.error = None
        self._started_monotonic = None if observed else self.clock()
        self._result_monotonic = None
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
        self.finished_at = self.now()
        self.state = "error" if error else "success"
        self.error = error
        self._result_monotonic = self.clock() if not error else None
        self._started_monotonic = None
        self.publish()
        return True

    def collected(self, timestamp: str) -> None:
        self.last_collection_at = timestamp
        now = self.clock()
        if (self._last_collection_publish is None or
                now - self._last_collection_publish >= COLLECTION_PUBLISH_SECONDS):
            self._last_collection_publish = now
            self.publish()

    def reset(self) -> None:
        self.state = "idle"
        self.operation = None
        self.started_at = None
        self.finished_at = None
        self.duration_seconds = None
        self.error = None
        self._started_monotonic = None
        self._result_monotonic = None
        self.publish()

    def tick(self) -> None:
        if self.state != "success":
            return
        if self._result_monotonic is None:
            return
        if self.clock() - self._result_monotonic < RESULT_SECONDS:
            return
        self.reset()
