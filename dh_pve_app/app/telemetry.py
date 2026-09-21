from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import time
import threading
import urllib.request
import uuid
from pathlib import Path
from typing import Callable, Mapping, Protocol

from .state_store import StateStore

PRODUCT = "digitalhouses_pve_agent"
SCHEMA_VERSION = 1
TELEMETRY_POLICY_VERSION = 1
BASE_URL = "https://telemetry.digitalhouses.vip"
NORMAL_INTERVAL_SECONDS = 24 * 60 * 60
JITTER_SECONDS = 30 * 60
FAILURE_BACKOFF_SECONDS = 60 * 60
RUNNER_CHECK_SECONDS = 60.0
HTTP_TIMEOUT_SECONDS = 5.0
_RELEASE_SOURCE_RE = re.compile(
    r"^digitalhouses_pve_agent-v(?P<version>"
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r")$"
)
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class TelemetryTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        path: str,
        payload: Mapping[str, object],
        token: str,
        timeout_seconds: float,
    ) -> int: ...


class UrllibTelemetryTransport:
    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def request(
        self,
        *,
        method: str,
        path: str,
        payload: Mapping[str, object],
        token: str,
        timeout_seconds: float,
    ) -> int:
        body = json.dumps(
            dict(payload),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "DigitalHouses-Telemetry/1",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return int(response.status)


def _valid_uuid4(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return parsed.version == 4 and str(parsed) == value.lower()


def _valid_token(value: object) -> bool:
    if not isinstance(value, str) or len(value) < 64:
        return False
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        return False
    return len(raw) >= 32


def _read_build_info(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    result: dict[str, str] = {}
    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def is_released_build(version: str, build_info_path: Path) -> bool:
    info = _read_build_info(build_info_path)
    if info.get("version") != version:
        return False
    source = info.get("source", "")
    match = _RELEASE_SOURCE_RE.fullmatch(source)
    if match is None or match.group("version") != version:
        return False
    return _SHA_RE.fullmatch(info.get("commit", "")) is not None


class TelemetryClient:
    def __init__(
        self,
        *,
        enabled: bool,
        version: str,
        state_store: StateStore,
        build_info_path: Path,
        transport: TelemetryTransport | None = None,
        now_epoch: Callable[[], float] = time.time,
    ) -> None:
        self.enabled = bool(enabled)
        self.version = version
        self.state_store = state_store
        self.build_info_path = build_info_path
        self.transport = transport or UrllibTelemetryTransport()
        self.now_epoch = now_epoch
        self.log = logging.getLogger(__name__)
        self._state = self._load_or_create_state()
        self.released_build = is_released_build(self.version, self.build_info_path)

    def _load_or_create_state(self) -> dict[str, object]:
        try:
            state = self.state_store.load()
        except Exception:
            state = {}
        installation_id = state.get("installation_id")
        installation_token = state.get("installation_token")
        changed = False
        if not _valid_uuid4(installation_id):
            installation_id = str(uuid.uuid4())
            state["installation_id"] = installation_id
            changed = True
        if not _valid_token(installation_token):
            installation_token = secrets.token_hex(32)
            state["installation_token"] = installation_token
            changed = True
        if state.get("schema_version") != 1:
            state["schema_version"] = 1
            changed = True
        if changed:
            self.state_store.save(state)
        try:
            self.state_store.path.chmod(0o600)
        except OSError:
            pass
        return dict(state)

    @property
    def installation_id(self) -> str:
        return str(self._state["installation_id"])

    @property
    def installation_token(self) -> str:
        return str(self._state["installation_token"])

    def _save(self) -> None:
        self.state_store.save(self._state)
        try:
            self.state_store.path.chmod(0o600)
        except OSError:
            pass

    def payload(self) -> dict[str, object]:
        return {
            "schema": SCHEMA_VERSION,
            "telemetry_policy_version": TELEMETRY_POLICY_VERSION,
            "installation_id": self.installation_id,
            "product": PRODUCT,
            "version": self.version,
        }

    def _normal_interval(self) -> float:
        digest = hashlib.sha256(self.installation_id.encode("ascii")).digest()
        bucket = int.from_bytes(digest[:4], "big")
        jitter = (bucket % (2 * JITTER_SECONDS + 1)) - JITTER_SECONDS
        return float(NORMAL_INTERVAL_SECONDS + jitter)

    @staticmethod
    def _number(value: object) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def _due(self, now: float) -> bool:
        last_attempt = self._number(self._state.get("last_attempt_epoch"))
        last_success = self._number(self._state.get("last_success_epoch"))
        if (
            last_attempt is not None
            and (last_success is None or last_attempt > last_success)
            and now - last_attempt < FAILURE_BACKOFF_SECONDS
        ):
            return False

        last_success = self._number(self._state.get("last_success_epoch"))
        last_version = self._state.get("last_reported_version")
        if last_success is None or last_version != self.version:
            return True
        return now >= last_success + self._normal_interval()

    def tick(self) -> bool:
        if not self.enabled:
            return False
        if not self.released_build:
            return False

        now = float(self.now_epoch())
        if not self._due(now):
            return False

        self._state["last_attempt_epoch"] = now
        self._save()
        try:
            status = self.transport.request(
                method="POST",
                path="/v1/heartbeat",
                payload=self.payload(),
                token=self.installation_token,
                timeout_seconds=HTTP_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            self.log.warning("Telemetry heartbeat failed; will retry later: %s", exc)
            return False

        if not 200 <= int(status) < 300:
            self.log.warning(
                "Telemetry heartbeat failed with HTTP %s; will retry later",
                status,
            )
            return False

        self._state["last_success_epoch"] = now
        self._state["last_reported_version"] = self.version
        self._save()
        return True

    def delete(self) -> bool:
        payload = {
            "schema": SCHEMA_VERSION,
            "installation_id": self.installation_id,
            "product": PRODUCT,
        }
        try:
            status = self.transport.request(
                method="DELETE",
                path="/v1/installation",
                payload=payload,
                token=self.installation_token,
                timeout_seconds=HTTP_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            self.log.warning("Telemetry deletion failed: %s", exc)
            return False

        if not (200 <= int(status) < 300 or int(status) == 404):
            self.log.warning("Telemetry deletion failed with HTTP %s", status)
            return False

        self._state.pop("last_success_epoch", None)
        self._state.pop("last_reported_version", None)
        self._state.pop("last_attempt_epoch", None)
        self._save()
        return True



class TelemetryRunner:
    """Run best-effort telemetry outside all product monitoring loops."""

    def __init__(
        self,
        client: TelemetryClient,
        *,
        check_seconds: float = RUNNER_CHECK_SECONDS,
    ) -> None:
        self.client = client
        self.check_seconds = float(check_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="dh-pve-telemetry",
            daemon=False,
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.client.tick()
            self._stop.wait(self.check_seconds)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join()
