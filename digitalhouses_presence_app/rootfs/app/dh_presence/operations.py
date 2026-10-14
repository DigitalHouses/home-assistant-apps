"""Runtime-owned, read-only Presence controls and published release checks."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from dh_presence.storage import atomic_json

RELEASE_URL = "https://api.github.com/repos/DigitalHouses/home-assistant-apps/releases?per_page=100"
RELEASE_RE = re.compile(r"^digitalhouses_presence_app-v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_latest_release(releases: object) -> str | None:
    if not isinstance(releases, list):
        raise ValueError("Unexpected GitHub Releases payload")
    versions = []
    for item in releases:
        if not isinstance(item, dict) or item.get("draft") or item.get("prerelease"):
            continue
        tag = item.get("tag_name")
        match = RELEASE_RE.fullmatch(tag) if isinstance(tag, str) else None
        if match:
            versions.append((tuple(map(int, match.groups())), ".".join(match.groups())))
    return max(versions)[1] if versions else None


def fetch_latest_release(timeout: int = 10) -> str | None:
    request = Request(RELEASE_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "DigitalHouses-Presence-App",
    })
    with urlopen(request, timeout=timeout) as response:
        return find_latest_release(json.load(response))


def is_newer(current: str, latest: str | None) -> bool | None:
    if latest is None:
        return None
    current_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", current)
    latest_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", latest)
    if not current_match or not latest_match:
        return None
    return tuple(map(int, latest_match.groups())) > tuple(map(int, current_match.groups()))


class Operations:
    """Foreground card is volatile; successful manual refresh is durable."""
    def __init__(self, path: str):
        self.path = path
        try:
            state = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            state = {"schema_version": 1, "last_refresh": None}
        if (not isinstance(state, dict) or state.get("schema_version") != 1
                or not (state.get("last_refresh") is None or isinstance(state.get("last_refresh"), str))):
            raise ValueError("Corrupt Presence refresh history")
        self.last_refresh = state["last_refresh"]
        self.state = "idle"
        self.operation = None
        self.started_at = None
        self.finished_at = None
        self.duration_seconds = None
        self.error = None
        self._began = None
        self._success_at = None
        self.refresh_state = "idle"

    def begin(self, operation: str) -> bool:
        if self.state == "running" or operation not in ("refresh", "check"):
            return False
        self.state = "running"
        self.operation = operation
        self.started_at = utc_now()
        self.finished_at = None
        self.duration_seconds = None
        self.error = None
        self._began = time.monotonic()
        self._success_at = None
        if operation == "refresh":
            self.refresh_state = "updating"
        return True

    def finish(self, error: str | None = None, *, refresh_succeeded: bool = False):
        if self.state != "running":
            raise ValueError("No foreground operation in progress")
        if refresh_succeeded and self.operation != "refresh":
            raise ValueError("Refresh success requires refresh operation")
        if refresh_succeeded and error is None:
            now = utc_now()
            atomic_json(self.path, {"schema_version": 1, "last_refresh": now})
            self.last_refresh = now
        self.finished_at = utc_now()
        self.duration_seconds = round(max(0, time.monotonic() - self._began), 2)
        self.error = error
        self.state = "error" if error else "success"
        self._success_at = time.monotonic() if not error else None
        if self.operation == "refresh":
            self.refresh_state = "error" if error else "idle"

    def tick(self) -> bool:
        if self.state == "success" and self._success_at is not None and time.monotonic() - self._success_at >= 5:
            self.state = "idle"
            self.operation = None
            self.started_at = None
            self.finished_at = None
            self.duration_seconds = None
            self.error = None
            self._success_at = None
            return True
        return False

    def snapshot(self):
        return {
            "card": {
                "state": self.state,
                "operation": self.operation,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "duration_seconds": self.duration_seconds,
                "error": self.error,
            },
            "refresh_state": self.refresh_state,
            "last_refresh": self.last_refresh,
        }
