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

from .state_store import StateStore, StateStoreError
from .auto_update import AutoUpdatePreference

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
        self.auto_update_preference = AutoUpdatePreference(state_dir)
        self.auto_update = False
        self._auto_install_pending = False
        self._check_on_enable_pending = False
        self._auto_preference_error: str | None = None
        self._lock = threading.Lock()
        self._last_check = 0.0
        self._checking = False
        self._check_error: str | None = None
        self._check_result: tuple[str, str] | None = None
        self._check_start_mono: float | None = None
        self._check_started_at: str | None = None
        self._check_duration: float | None = None
        self._published: str | None = None
        self._status_error: str | None = None
        self._status: str = "idle"
        try:
            cached = self.cache.load()
            self.tag = str(cached.get("tag") or "")
            self.latest = str(cached.get("version") or "unknown")
            self.checked = str(cached.get("checked_at") or "")
            self._check_started_at = cached.get("check_started_at")
            self._check_duration = cached.get("check_duration_seconds")
        except Exception as exc:
            log.warning("Invalid update cache: %s", exc)
            self.tag, self.latest, self.checked = "", "unknown", ""
            self._check_started_at = None
            self._check_duration = None
        self.known = False  # A stale cached check is never proof of availability.

    def start_check(self) -> bool:
        with self._lock:
            if self._checking or self._is_worker_busy():
                return False
            self._checking = True
            self._status = "checking"
            self._status_error = None
            self._last_check = time.monotonic()
            self._check_start_mono = self._last_check
            self._check_started_at = datetime.now(timezone.utc).isoformat()
            self._check_duration = None
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
            self._check_duration = round(max(0, time.monotonic() - (
                self._check_start_mono if self._check_start_mono is not None else time.monotonic()
            )), 3)
            self._checking = False

    def _is_worker_busy(self) -> bool:
        try:
            return self.worker.load().get("state") in BUSY_PHASES
        except Exception:
            return True  # Fail closed if install status cannot be read.

    def _apply_check(self) -> bool:
        with self._lock:
            if self._checking or (self._check_result is None and self._check_error is None):
                return False
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
            self.cache.save({
                "tag": self.tag, "version": self.latest, "checked_at": self.checked,
                "check_started_at": self._check_started_at,
                "check_duration_seconds": self._check_duration,
            })
        except Exception as exc:
            log.warning("Update cache save failed: %s", exc)
        return error is None

    def _worker_status(self) -> dict[str, object]:
        try:
            return self.worker.load()
        except Exception as exc:
            return {"state": "error", "error": f"Update status unreadable: {exc}"}

    def _payload(self) -> dict[str, object]:
        worker = self._worker_status()
        worker_state = worker.get("state")
        # A terminal install result is historical after a newer successful
        # release check. Preserve it separately as installation_status, but
        # do not label a fresh "no updates" check as a new installation.
        worker_is_latest = True
        if self.known and self.checked:
            try:
                checked_at = datetime.fromisoformat(self.checked)
                updated_at = datetime.fromisoformat(str(worker.get("updated_at")))
                worker_is_latest = updated_at > checked_at
            except (TypeError, ValueError):
                worker_is_latest = False
        if worker_state in BUSY_PHASES:
            status = worker_state
            error = worker.get("error")
        else:
            status, error = self._status, self._status_error
        if self._checking and worker_state not in BUSY_PHASES:
            status, error = "checking", None
        elif (
            worker_state in {"completed", "error"}
            and self._status == "idle"
            and worker_is_latest
        ):
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
            "check_started_at": self._check_started_at,
            "check_duration_seconds": self._check_duration,
            "installed_version": self.version,
            "auto_update": self.auto_update,
            "installation_status": worker_state,
            "installation_error": worker.get("error"),
        }

    def installation_view(self) -> tuple[str, str | None]:
        """Current installer facts, independent of any foreground card history."""
        try:
            worker = self.worker.load()
        except (OSError, StateStoreError):
            log.warning("Cannot read installer state for UI", exc_info=True)
            return "unknown", None
        state = worker.get("state")
        if state in BUSY_PHASES:
            return "running", None
        if state == "error":
            # A failed older update is no longer relevant once its target (or
            # a newer version) is actually installed. No timestamp matching.
            try:
                target = self.request.load().get("version")
                if isinstance(target, str) and stable_version(self.version) >= stable_version(target):
                    return "idle", None
            except (OSError, ValueError, TypeError, StateStoreError):
                log.warning("Cannot read installation target for diagnostics")
            return "error", str(worker.get("error") or "Update failed")
        return ("completed" if state == "completed" else "idle"), None

    def sync_install_card(self, card, *, startup: bool = False, requested: bool = False) -> None:
        """Project the actual worker, not a restored UI transaction."""
        state, error = self.installation_view()
        if state == "running":
            if card.operation != "install" or card.state != "running":
                if card.state == "running":
                    card.reset()
                card.begin("install", observed=True)
            return
        if requested and self._status == "error":
            error = self._status_error or "Update failed"
        if card.state == "running" and card.operation == "install":
            if error or state == "completed":
                card.finish("install", error=error)
            else:
                card.reset()
        elif startup and state == "error":
            card.begin("install", observed=True)
            card.finish("install", error=error)

    def tick(self, bridge: object, *, check: bool = False, install: bool = False,
             denial_reason: Callable[[], str | None] | None = None,
             allow_auto_install: bool = True) -> None:
        # Read the same persisted preference as CLI, even if CLI changed it
        # while the agent was running. Fail closed on invalid state.
        previously_enabled = self.auto_update
        try:
            self.auto_update = self.auto_update_preference.enabled()
            self._auto_preference_error = None
        except (StateStoreError, OSError) as exc:
            self.auto_update = False
            error = str(exc)
            if error != self._auto_preference_error:
                log.error("Auto-update disabled: %s", error)
            self._auto_preference_error = error
        # OFF -> ON triggers a fresh verification immediately, rather than
        # waiting for the next 24-hour check. An in-flight or just-completed
        # check is already fresh and must not be duplicated.
        if self.auto_update and not previously_enabled and not (
            self._checking or self._check_result is not None
        ):
            self._check_on_enable_pending = True
        checked_successfully = self._apply_check()
        if not self.auto_update:
            self._auto_install_pending = False
            self._check_on_enable_pending = False
        elif checked_successfully and self._payload()["available"]:
            self._auto_install_pending = True
        # Consume once after a fresh check; a denied UPS preflight must not
        # spin an update attempt on every collector iteration.
        if allow_auto_install and self._auto_install_pending:
            self._auto_install_pending = False
            install = True
        if check or self._check_on_enable_pending or self._last_check == 0 or (
            time.monotonic() - self._last_check >= CHECK_INTERVAL
        ):
            if self.start_check():
                self._check_on_enable_pending = False
        if install:
            if self._checking or not self.known or not self.tag or not self._payload()["available"]:
                self._status, self._status_error = "error", "No verified newer release"
            elif self._is_worker_busy():
                log.info("Update already running; duplicate request ignored")
            else:
                try:
                    denied = denial_reason() if denial_reason is not None else "UPS preflight not provided"
                except Exception as exc:
                    # Fail closed: broken safety checks must not crash the
                    # main agent loop or permit an unsafe UPS interruption.
                    denied = f"UPS preflight failed: {exc}"
                    log.exception("Agent update UPS preflight failed")
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
            self.worker.save({
                "state": "queued", "error": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
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
            self.worker.save({
                "state": "error",
                "error": f"Unable to start update service: {exc}",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            log.error("Unable to start update service: %s", exc)
