"""Plex Agent release checks and an unprivileged update-request producer.

Network release checks run in a dedicated thread; only the independent
root-owned updater may replace the installed agent runtime.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .state_store import StateStore

log = logging.getLogger(__name__)
PRODUCT = "digitalhouses_plex_agent"
RELEASES_URL = "https://api.github.com/repos/DigitalHouses/home-assistant-apps/releases"
STABLE_TAG = re.compile(r"^digitalhouses_plex_agent-v(\d+)\.(\d+)\.(\d+)$")
CHECK_INTERVAL = 24 * 3600
BUSY_PHASES = {"queued", "downloading", "installing", "verifying", "rolling_back"}


def stable_version(value: str) -> tuple[int, int, int]:
    if re.fullmatch(r"\d+\.\d+\.\d+", value) is None:
        raise ValueError("Invalid stable version")
    return tuple(int(part) for part in value.split("."))


def latest_release(*, opener=urllib.request.urlopen) -> tuple[str, str]:
    selected = None
    highest = None
    for page in range(1, 11):
        request = urllib.request.Request(
            f"{RELEASES_URL}?per_page=100&page={page}",
            headers={"User-Agent": "DigitalHouses-Plex-Agent",
                     "Accept": "application/vnd.github+json"},
        )
        with opener(request, timeout=12) as response:
            releases = json.load(response)
        if not isinstance(releases, list):
            raise ValueError("Unexpected GitHub Releases response")
        for release in releases:
            if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
                continue
            tag = release.get("tag_name")
            match = STABLE_TAG.fullmatch(tag) if isinstance(tag, str) else None
            if match is None or not release.get("published_at"):
                continue
            version = tuple(int(x) for x in match.groups())
            if highest is None or version > highest:
                highest = version
                selected = (tag, ".".join(match.groups()))
        if len(releases) < 100:
            if selected is None:
                raise ValueError("No published stable Plex Agent release")
            return selected
    raise ValueError("GitHub release pagination limit exceeded")


class UpdateManager:
    def __init__(self, state_dir: Path, version: str) -> None:
        self.dir = state_dir
        self.version = version
        self.request = StateStore(state_dir / "update_request.json")
        self.worker = StateStore(Path("/var/lib/digitalhouses-plex-updater/update_worker.json"))
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._pending: tuple[tuple[str, str] | None, str | None, float] | None = None
        self._start_time = 0.0
        self._last_check = 0.0
        self._check_manual = False
        self._last_payload = None
        self.tag = ""
        self.latest = "unknown"
        self.known = False
        self.status = "idle"
        self.error: str | None = None
        self.checked_at: str | None = None
        self.duration_seconds: float | None = None

    def start_check(self, *, manual: bool = False) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            try:
                if self.worker.load().get("state") in BUSY_PHASES:
                    return False
            except Exception:
                return False
            self._start_time = time.monotonic()
            self._last_check = self._start_time
            self.status, self.error = "checking", None
            self._check_manual = manual
            self._pending = None
            self._thread = threading.Thread(
                target=self._fetch, name="plex-update-check", daemon=True
            )
            self._thread.start()
            return True

    def _fetch(self) -> None:
        try:
            result, error = latest_release(), None
        except Exception as exc:
            result, error = None, str(exc)
            log.warning("Plex release check failed: %s", type(exc).__name__)
        with self._lock:
            self._pending = (result, error, time.monotonic() - self._start_time)

    def poll(self) -> tuple[bool, str | None] | None:
        """Consume a completed *manual* check, returning its outcome for AgentCard."""
        with self._lock:
            pending = self._pending
            self._pending = None
            if pending is not None:
                self._thread = None
        if pending is None:
            if self._last_check == 0 or (
                time.monotonic() - self._last_check >= CHECK_INTERVAL
            ):
                self.start_check()
            return None
        result, error, duration = pending
        self.checked_at = datetime.now(timezone.utc).isoformat()
        self.duration_seconds = round(duration, 3)
        self.known = error is None
        self.tag, self.latest = result if result is not None else ("", "unknown")
        self.status, self.error = ("error", error) if error else ("idle", None)
        was_manual = self._check_manual
        self._check_manual = False
        return (error is None, error) if was_manual else None

    def payload(self) -> dict[str, object]:
        try:
            worker = self.worker.load()
        except Exception:
            worker = {"state": "error", "error": "Update worker status unreadable"}
        busy = worker.get("state") in BUSY_PHASES
        return {
            "latest_version": self.latest,
            "available": stable_version(self.latest) > stable_version(self.version) if self.known else None,
            "status": worker.get("state") if busy else self.status,
            "error": worker.get("error") if busy else self.error,
            "checked_at": self.checked_at,
            "check_duration_seconds": self.duration_seconds,
        }

    def publish_if_changed(self, publisher, *, force: bool = False) -> None:
        data = self.payload()
        if force or data != self._last_payload:
            if publisher(data):
                self._last_payload = data

    def begin_install(self) -> tuple[bool, str | None]:
        data = self.payload()
        if data["available"] is not True or not self.tag:
            return False, "Нет подтверждённого нового релиза"
        try:
            if self.worker.load().get("state") in BUSY_PHASES:
                return False, "Обновление уже выполняется"
            requested_at = datetime.now(timezone.utc).isoformat()
            self.request.save({
                "tag": self.tag, "version": self.latest,
                "requested_at": requested_at,
            })
            (self.dir / "update-install-request").write_text(
                "install\n", encoding="ascii"
            )
        except Exception as exc:
            return False, f"Не удалось запросить установку: {type(exc).__name__}"
        return True, None

    def install_outcome(self, *, started_at: str | None) -> tuple[bool, str | None] | None:
        try:
            request = self.request.load()
            worker = self.worker.load()
            started = datetime.fromisoformat(str(started_at))
            requested = datetime.fromisoformat(str(request.get("requested_at")))
            if not (started.tzinfo and requested.tzinfo and requested >= started):
                return False, "Неверный идентификатор установки"
            if worker.get("state") in BUSY_PHASES:
                return None
            try:
                finished = datetime.fromisoformat(str(worker.get("updated_at")))
            except (TypeError, ValueError):
                finished = None
            if finished is None or not finished.tzinfo or finished < requested:
                # The independent systemd worker is started asynchronously.
                # A missing/old status is normal immediately after the button
                # press; only report a failure if the worker never starts.
                elapsed = (datetime.now(timezone.utc) - requested).total_seconds()
                if elapsed >= 60:
                    return False, "Служба обновления не запустилась за 60 секунд"
                return None
            if worker.get("state") == "error":
                return False, str(worker.get("error") or "Ошибка обновления")
            if worker.get("state") == "completed":
                if stable_version(self.version) >= stable_version(str(request.get("version"))):
                    return True, None
                return False, "Версия агента не соответствует установленной"
        except Exception:
            return False, "Не удалось проверить результат установки"
        return None
