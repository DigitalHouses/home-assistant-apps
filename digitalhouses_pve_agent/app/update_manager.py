"""Home Assistant update controls. Network checks never run on the collector thread."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .state_store import StateStore

log = logging.getLogger(__name__)
PRODUCT = "digitalhouses_pve_agent"
RELEASES_URL = "https://api.github.com/repos/DigitalHouses/home-assistant-apps/releases"
STABLE_TAG = re.compile(r"^digitalhouses_pve_agent-v(\d+)\.(\d+)\.(\d+)$")
UPDATE_SERVICE = "digitalhouses_pve_agent-update.service"
CHECK_INTERVAL = 24 * 60 * 60
BUSY_PHASES = {"queued", "downloading", "installing", "verifying", "rolling_back"}


def stable_version(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        raise ValueError(f"Not a stable version: {version}")
    return tuple(int(x) for x in match.groups())


def latest_release(*, opener=urllib.request.urlopen) -> tuple[str, str]:
    """Find the newest published stable PVE Release, never main or a tag alone."""
    latest: tuple[int, int, int] | None = None
    selected: tuple[str, str] | None = None
    for page in range(1, 11):
        request = urllib.request.Request(
            f"{RELEASES_URL}?per_page=100&page={page}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "DigitalHouses-PVE-Agent"},
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
            if latest is None or version > latest:
                latest, selected = version, (tag, ".".join(match.groups()))
        if len(releases) < 100:
            if selected is None:
                raise ValueError("No published stable PVE release found")
            return selected
    raise ValueError("GitHub Releases pagination limit reached")


class UpdateManager:
    def __init__(self, state_dir: Path, version: str) -> None:
        self.state_dir = state_dir
        self.version = version
        self.cache = StateStore(state_dir / "update_check.json")
        self.request = StateStore(state_dir / "update_request.json")
        self.worker = StateStore(state_dir / "update_worker.json")
        self._lock = threading.Lock()
        self._last_check = 0.0
        self._checking = False
        self._check_error: str | None = None
        self._check_result: tuple[str, str] | None = None
        self._published: str | None = None
        self._status_error: str | None = None
        self._status: str = "idle"
        self._worker_stamp: str | None = None
        try:
            cached = self.cache.load()
            self.tag = str(cached.get("tag") or "")
            self.latest = str(cached.get("version") or "unknown")
            self.checked = str(cached.get("checked_at") or "")
        except Exception as exc:
            log.warning("Invalid update cache: %s", exc)
            self.tag, self.latest, self.checked = "", "unknown", ""
        self.known = False  # A stale cached check is never proof of availability.

    def start_check(self) -> bool:
        with self._lock:
            if self._checking or self._is_worker_busy():
                return False
            self._checking = True
            self._status = "checking"
            self._status_error = None
            self._last_check = time.monotonic()
        threading.Thread(target=self._fetch_release, name="pve-update-check", daemon=True).start()
        return True

    def _fetch_release(self) -> None:
        try:
            result = latest_release()
            error = None
        except Exception as exc:
            result, error = None, str(exc)
            log.warning("Update check failed: %s", error)
        with self._lock:
            self._check_result = result
            self._check_error = error
            self._checking = False

    def _is_worker_busy(self) -> bool:
        try:
            return self.worker.load().get("state") in BUSY_PHASES
        except Exception:
            return True  # Fail closed if install status cannot be read.

    def _apply_check(self) -> None:
        with self._lock:
            if self._checking or (self._check_result is None and self._check_error is None):
                return
            result, error = self._check_result, self._check_error
            self._check_result, self._check_error = None, None
        self.checked = datetime.now(timezone.utc).isoformat()
        if error is not None:
            self.tag, self.latest, self.known = "", "unknown", False
            self._status, self._status_error = "error", error
        else:
            assert result is not None
            self.tag, self.latest = result
            self.known = True
            self._status, self._status_error = "idle", None
        try:
            self.cache.save({"tag": self.tag, "version": self.latest, "checked_at": self.checked})
        except Exception as exc:
            log.warning("Update cache save failed: %s", exc)

    def _worker_status(self) -> dict[str, object]:
        try:
            return self.worker.load()
        except Exception as exc:
            return {"state": "error", "error": f"Update status unreadable: {exc}"}

    def _payload(self) -> dict[str, object]:
        worker = self._worker_status()
        worker_state = worker.get("state")
        if worker_state in BUSY_PHASES:
            status = worker_state
            error = worker.get("error")
        else:
            status, error = self._status, self._status_error
        if self._checking and worker_state not in BUSY_PHASES:
            status, error = "checking", None
        elif worker_state in {"completed", "error"} and self._status == "idle":
            status, error = worker_state, worker.get("error")
        available = (
            (stable_version(self.latest) > stable_version(self.version))
            if self.known else None
        )
        return {
            "latest_version": self.latest if self.known else "unknown",
            "available": available,
            "status": status,
            "error": error,
            "checked_at": self.checked or None,
            "installed_version": self.version,
        }

    def tick(self, bridge: object, *, check: bool = False, install: bool = False,
             denial_reason: Callable[[], str | None] | None = None) -> None:
        self._apply_check()
        if check or self._last_check == 0 or (
            time.monotonic() - self._last_check >= CHECK_INTERVAL
        ):
            self.start_check()
        if install:
            if self._checking or not self.known or not self.tag or not self._payload()["available"]:
                self._status, self._status_error = "error", "No verified newer release"
            elif self._is_worker_busy():
                log.info("Update already running; duplicate request ignored")
            else:
                denied = denial_reason() if denial_reason else "UPS preflight not provided"
                if denied:
                    self._status, self._status_error = "error", denied
                    log.warning("Agent update denied: %s", denied)
                else:
                    self._launch_update()
        payload = self._payload()
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if serialized != self._published:
            if bridge.publish_update_state(payload):
                self._published = serialized

    def publish(self, bridge: object) -> None:
        payload = self._payload()
        if bridge.publish_update_state(payload):
            self._published = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _launch_update(self) -> None:
        try:
            self.request.save({
                "tag": self.tag, "version": self.latest,
                "requested_at": datetime.now(timezone.utc).isoformat(),
            })
            # Clear the previous result so it cannot hide the queued operation.
            self.worker.save({"state": "queued", "error": None})
        except Exception as exc:
            self._status, self._status_error = "error", str(exc)
            log.error("Update request persistence failed: %s", exc)
            return
        try:
            subprocess.run(
                ["systemctl", "start", "--no-block", UPDATE_SERVICE],
                check=True, capture_output=True, text=True, timeout=8,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            self.worker.save({"state": "error", "error": f"Unable to start update service: {exc}"})
            log.error("Unable to start update service: %s", exc)
