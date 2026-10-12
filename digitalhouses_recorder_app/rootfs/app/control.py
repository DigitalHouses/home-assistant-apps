"""Compact UI controls and stable release checks for Recorder App."""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from datetime import datetime, timezone
from typing import Callable

PRODUCT = "digitalhouses_recorder_app"
RELEASES_URL = "https://api.github.com/repos/DigitalHouses/home-assistant-apps/releases"
STABLE_TAG = re.compile(r"^digitalhouses_recorder_app-v(\d+)\.(\d+)\.(\d+)$")
CHECK_INTERVAL_SECONDS = 24 * 3600
RESULT_SECONDS = 5.0
OPERATIONS = frozenset({"refresh", "check"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_version(value: str) -> tuple[int, int, int]:
    if re.fullmatch(r"\d+\.\d+\.\d+", value) is None:
        raise ValueError("Invalid stable version")
    return tuple(int(part) for part in value.split("."))


def latest_release(*, opener=urllib.request.urlopen) -> tuple[str, str]:
    selected: tuple[str, str] | None = None
    highest: tuple[int, int, int] | None = None
    for page in range(1, 11):
        request = urllib.request.Request(
            f"{RELEASES_URL}?per_page=100&page={page}",
            headers={
                "User-Agent": "DigitalHouses-Recorder-App",
                "Accept": "application/vnd.github+json",
            },
        )
        with opener(request, timeout=12) as response:
            releases = json.load(response)
        if not isinstance(releases, list):
            raise ValueError("Unexpected GitHub Releases response")
        for release in releases:
            if (
                not isinstance(release, dict)
                or release.get("draft")
                or release.get("prerelease")
                or not release.get("published_at")
            ):
                continue
            tag = release.get("tag_name")
            match = STABLE_TAG.fullmatch(tag) if isinstance(tag, str) else None
            if match is None:
                continue
            version_tuple = tuple(int(part) for part in match.groups())
            if highest is None or version_tuple > highest:
                highest = version_tuple
                selected = (tag, ".".join(match.groups()))
        if len(releases) < 100:
            if selected is None:
                raise ValueError("No published stable Recorder App release")
            return selected
    raise ValueError("GitHub release pagination limit exceeded")


class ReleaseChecker:
    """Thread-safe state for manual/background release checks."""

    def __init__(
        self,
        version: str,
        *,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], str] = utc_now,
    ) -> None:
        stable_version(version)
        self.version = version
        self.clock = clock
        self.now = now
        self._lock = threading.Lock()
        self._started_monotonic: float | None = None
        self.latest = "unknown"
        self.available: bool | None = None
        self.status = "idle"
        self.error: str | None = None
        self.checked_at: str | None = None
        self.duration_seconds: float | None = None

    def begin(self) -> bool:
        with self._lock:
            if self.status == "checking":
                return False
            self.status = "checking"
            self.error = None
            self._started_monotonic = self.clock()
            return True

    def complete(
        self,
        *,
        opener=urllib.request.urlopen,
    ) -> tuple[bool, str | None]:
        with self._lock:
            if self.status != "checking" or self._started_monotonic is None:
                return False, "Release check was not started"
            started = self._started_monotonic

        try:
            _tag, latest = latest_release(opener=opener)
            available = stable_version(latest) > stable_version(self.version)
            error = None
        except Exception as exc:
            latest = "unknown"
            available = None
            error = str(exc) or exc.__class__.__name__

        duration = round(max(0.0, self.clock() - started), 3)
        with self._lock:
            self.latest = latest
            self.available = available
            self.status = "error" if error else "idle"
            self.error = error
            self.checked_at = self.now()
            self.duration_seconds = duration
            self._started_monotonic = None
        return error is None, error

    def payload(self) -> dict[str, object]:
        with self._lock:
            return {
                "latest_version": self.latest,
                "available": self.available,
                "status": self.status,
                "error": self.error,
                "checked_at": self.checked_at,
                "check_duration_seconds": self.duration_seconds,
            }


class AppCard:
    """Transient user-operation state for the compact Home Assistant card."""

    def __init__(
        self,
        publisher: Callable[[dict[str, object]], bool],
        *,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], str] = utc_now,
        result_seconds: float = RESULT_SECONDS,
    ) -> None:
        self.publisher = publisher
        self.clock = clock
        self.now = now
        self.result_seconds = float(result_seconds)
        self._lock = threading.Lock()
        self._generation = 0
        self._started_monotonic: float | None = None
        self.state = "idle"
        self.operation: str | None = None
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.duration_seconds: float | None = None
        self.error: str | None = None

    def payload(self) -> dict[str, object]:
        with self._lock:
            return {
                "state": self.state,
                "operation": self.operation,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "duration_seconds": self.duration_seconds,
                "error": self.error,
            }

    def publish(self) -> bool:
        return bool(self.publisher(self.payload()))

    def begin(self, operation: str) -> bool:
        if operation not in OPERATIONS:
            raise ValueError(f"Unsupported operation: {operation}")
        with self._lock:
            if self.state == "running":
                return False
            self._generation += 1
            self.operation = operation
            self.state = "running"
            self.started_at = self.now()
            self.finished_at = None
            self.duration_seconds = None
            self.error = None
            self._started_monotonic = self.clock()
        self.publish()
        return True

    def finish(
        self,
        operation: str,
        *,
        error: str | None = None,
        measured_seconds: float | None = None,
    ) -> bool:
        with self._lock:
            if self.state != "running" or self.operation != operation:
                return False
            if measured_seconds is not None:
                duration = max(0.0, float(measured_seconds))
            elif self._started_monotonic is not None:
                duration = max(0.0, self.clock() - self._started_monotonic)
            else:
                duration = 0.0
            self.duration_seconds = round(duration, 3)
            self.finished_at = self.now()
            self.state = "error" if error else "success"
            self.error = error
            self._started_monotonic = None
            generation = self._generation
        self.publish()

        if error is None:
            timer = threading.Timer(
                self.result_seconds,
                self._reset_success,
                args=(generation,),
            )
            timer.daemon = True
            timer.start()
        return True

    def _reset_success(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation or self.state != "success":
                return
            self.state = "idle"
            self.operation = None
            self.started_at = None
            self.finished_at = None
            self.duration_seconds = None
            self.error = None
        self.publish()
