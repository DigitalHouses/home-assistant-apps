"""Best-effort, explicitly opted-in DigitalHouses Presence App telemetry.

Protocol v1 / policy v1 is a transitional opt-in client: mandatory policy v2
is still under the repository's public-rollout legal hold. No resident or
device data crosses this boundary.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Callable, Mapping, Protocol

PRODUCT = "digitalhouses_presence_app"
BASE_URL = "https://telemetry.digitalhouses.vip"
STATE_FILE = Path("/data/telemetry.json")
INTERVAL_SECONDS = 24 * 3600
JITTER_SECONDS = 30 * 60
FAILURE_BACKOFF_SECONDS = 3600
HTTP_TIMEOUT_SECONDS = 5
CHECK_SECONDS = 60
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
LOG = logging.getLogger("dh_presence_app.telemetry")


class TelemetryStateError(ValueError):
    """A stored installation identity is invalid, never silently replaced."""


class Transport(Protocol):
    def request(self, *, method: str, path: str, payload: Mapping[str, object],
                token: str, timeout_seconds: float) -> int: ...


class HTTPS:
    def request(self, *, method: str, path: str, payload: Mapping[str, object],
                token: str, timeout_seconds: float) -> int:
        req = urllib.request.Request(
            BASE_URL + path,
            data=json.dumps(dict(payload), separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method=method,
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            return int(response.status)


class TelemetryClient:
    def __init__(self, *, version: str, enabled: bool,
                 state_file: Path = STATE_FILE, transport: Transport | None = None,
                 now_epoch: Callable[[], float] = time.time) -> None:
        self.version = version
        self.enabled = enabled
        self.state_file = state_file
        self.transport = transport if transport is not None else HTTPS()
        self.now_epoch = now_epoch
        self._lock = threading.Lock()
        # Consent must precede creation of the persistent anonymous identity.
        self.state = self._load_or_create() if enabled else None

    def _save(self) -> None:
        assert self.state is not None
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        path = self.state_file.with_name(self.state_file.name + "." + uuid.uuid4().hex + ".tmp")
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(self.state, out, separators=(",", ":"), sort_keys=True)
            os.replace(path, self.state_file)
            self.state_file.chmod(0o600)
        finally:
            if path.exists():
                path.unlink()

    def _load_or_create(self) -> dict[str, object]:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.state = {
                "schema_version": 1,
                "installation_id": str(uuid.uuid4()),
                "installation_token": secrets.token_hex(32),
            }
            self._save()
            return self.state
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TelemetryStateError("telemetry identity file unreadable or malformed") from exc

        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise TelemetryStateError("telemetry.schema_version must be 1")
        identifier = data.get("installation_id")
        try:
            parsed = uuid.UUID(identifier) if isinstance(identifier, str) else None
        except ValueError:
            parsed = None
        if parsed is None or parsed.version != 4 or str(parsed) != identifier:
            raise TelemetryStateError("telemetry.installation_id must be canonical UUIDv4")
        token = data.get("installation_token")
        try:
            valid_token = isinstance(token, str) and len(bytes.fromhex(token)) >= 32
        except ValueError:
            valid_token = False
        if not valid_token:
            raise TelemetryStateError("telemetry.installation_token must have at least 256 bits")
        for key in ("last_success_epoch", "last_attempt_epoch"):
            value = data.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                raise TelemetryStateError("telemetry." + key + " must be numeric")
        version = data.get("last_reported_version")
        if version is not None and (not isinstance(version, str) or not version):
            raise TelemetryStateError("telemetry.last_reported_version must be a version string")
        return data

    def _payload(self) -> dict[str, object]:
        assert self.state is not None
        return {
            "schema": 1,
            "telemetry_policy_version": 1,
            "installation_id": self.state["installation_id"],
            "product": PRODUCT,
            "version": self.version,
        }

    def _interval(self) -> int:
        assert self.state is not None
        digest = hashlib.sha256(str(self.state["installation_id"]).encode("ascii")).digest()
        jitter = int.from_bytes(digest[:4], "big") % (2 * JITTER_SECONDS + 1) - JITTER_SECONDS
        return INTERVAL_SECONDS + jitter

    def _due(self, now: float) -> bool:
        assert self.state is not None
        attempt = self.state.get("last_attempt_epoch")
        success = self.state.get("last_success_epoch")
        if attempt is not None and (success is None or attempt > success):
            if now < float(attempt) + FAILURE_BACKOFF_SECONDS:
                return False
        if success is None or self.state.get("last_reported_version") != self.version:
            return True
        return now >= float(success) + self._interval()

    def tick(self) -> bool:
        if not self.enabled or self.state is None:
            return False
        # Never report arbitrary local builds under a canonical release identity.
        if not SEMVER.fullmatch(self.version) or self.version.endswith("-local"):
            return False
        with self._lock:
            now = float(self.now_epoch())
            if not self._due(now):
                return False
            self.state["last_attempt_epoch"] = now
            self._save()
            try:
                status = self.transport.request(
                    method="POST", path="/v1/heartbeat",
                    payload=self._payload(),
                    token=str(self.state["installation_token"]),
                    timeout_seconds=HTTP_TIMEOUT_SECONDS,
                )
                if not 200 <= int(status) < 300:
                    LOG.warning("Telemetry heartbeat HTTP %s; retry after backoff", status)
                    return False
            except urllib.error.HTTPError as exc:
                LOG.warning("Telemetry heartbeat HTTP %s; check Stats server product allowlist and request schema; retry after backoff", exc.code)
                return False
            except Exception as exc:
                LOG.warning("Telemetry heartbeat delivery failed; retry after backoff: %s", type(exc).__name__)
                return False
            self.state["last_success_epoch"] = now
            self.state["last_reported_version"] = self.version
            self._save()
            LOG.info("Telemetry heartbeat accepted: product=%s version=%s", PRODUCT, self.version)
            return True

    def delete(self) -> bool:
        """Authenticated erasure; a still-consenting client receives a new identity."""
        if self.state is None:
            return False
        with self._lock:
            try:
                status = self.transport.request(
                    method="DELETE", path="/v1/installation",
                    payload={
                        "schema": 1,
                        "installation_id": self.state["installation_id"],
                        "product": PRODUCT,
                    },
                    token=str(self.state["installation_token"]),
                    timeout_seconds=HTTP_TIMEOUT_SECONDS,
                )
            except urllib.error.HTTPError as exc:
                status = exc.code
                if status != 404:
                    LOG.warning("Telemetry erasure request failed: HTTP %s", status)
                    return False
            except Exception as exc:
                LOG.warning("Telemetry erasure request failed: %s", type(exc).__name__)
                return False
            if not (200 <= int(status) < 300 or int(status) == 404):
                LOG.warning("Telemetry erasure request failed: HTTP %s", status)
                return False
            self.state = {
                "schema_version": 1,
                "installation_id": str(uuid.uuid4()),
                "installation_token": secrets.token_hex(32),
            }
            self._save()
            LOG.info("Previous telemetry installation record deleted and identity rotated")
            return True


class TelemetryRunner:
    def __init__(self, client: TelemetryClient, check_seconds: float = CHECK_SECONDS) -> None:
        self.client = client
        self.check_seconds = check_seconds
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="dh-presence-telemetry", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.client.tick()
            except (OSError, TelemetryStateError, ValueError) as exc:
                LOG.warning("Telemetry scheduling error; presence continues: %s", type(exc).__name__)
            self.stop_event.wait(self.check_seconds)

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=HTTP_TIMEOUT_SECONDS + 2)

if __name__ == "__main__":
    # Operator-only erasure: first disable telemetry in App config and restart.
    # Running this on an actively consenting App may result in a fresh heartbeat.
    import sys

    if sys.argv[1:] != ["--delete"]:
        raise SystemExit("Usage: python3 /app/telemetry.py --delete")
    if not STATE_FILE.exists():
        print("No local telemetry installation exists")
        raise SystemExit(0)
    client = TelemetryClient(
        version=os.environ.get("APP_VERSION", "0.1.40"),
        enabled=True,
    )
    if not client.delete():
        raise SystemExit("Telemetry deletion failed; local credentials retained")
    STATE_FILE.unlink()
    print("Telemetry installation deleted locally and on the server")
