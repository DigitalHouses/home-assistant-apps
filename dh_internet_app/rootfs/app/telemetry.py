from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

PRODUCT = "digitalhouses_internet_app"
SCHEMA_VERSION = 1
TELEMETRY_POLICY_VERSION = 1
BASE_URL = "https://telemetry.digitalhouses.vip"
STATE_FILE = Path("/data/telemetry.json")
NORMAL_INTERVAL_SECONDS = 24 * 60 * 60
JITTER_SECONDS = 30 * 60
FAILURE_BACKOFF_SECONDS = 60 * 60
RUNNER_CHECK_SECONDS = 60.0
HTTP_TIMEOUT_SECONDS = 5.0
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


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


class TelemetryClient:
    def __init__(
        self,
        *,
        enabled: bool,
        version: str,
        state_file: Path = STATE_FILE,
        transport: TelemetryTransport | None = None,
        now_epoch: Callable[[], float] = time.time,
    ) -> None:
        self.enabled = bool(enabled)
        self.version = version
        self.state_file = state_file
        self.transport = transport or UrllibTelemetryTransport()
        self.now_epoch = now_epoch
        self.log = logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._state = self._load_or_create_state()

    def _load_or_create_state(self) -> dict[str, Any]:
        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            state = {}
        if not isinstance(state, dict):
            state = {}

        changed = False
        installation_id = state.get("installation_id")
        try:
            parsed = uuid.UUID(str(installation_id))
            valid_id = (
                parsed.version == 4
                and str(parsed) == str(installation_id).lower()
            )
        except (ValueError, TypeError, AttributeError):
            valid_id = False
        if not valid_id:
            state["installation_id"] = str(uuid.uuid4())
            changed = True

        token = state.get("installation_token")
        try:
            token_valid = (
                isinstance(token, str)
                and len(bytes.fromhex(token)) >= 32
            )
        except ValueError:
            token_valid = False
        if not token_valid:
            state["installation_token"] = secrets.token_hex(32)
            changed = True

        if state.get("schema_version") != 1:
            state["schema_version"] = 1
            changed = True

        if changed:
            self._save_state(state)
        return dict(state)

    def _save_state(self, state: dict[str, Any] | None = None) -> None:
        if state is None:
            state = self._state
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                state,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        tmp.replace(self.state_file)
        try:
            self.state_file.chmod(0o600)
        except OSError:
            pass

    @property
    def installation_id(self) -> str:
        return str(self._state["installation_id"])

    @property
    def installation_token(self) -> str:
        return str(self._state["installation_token"])

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

        last_version = self._state.get("last_reported_version")
        if last_success is None or last_version != self.version:
            return True
        return now >= last_success + self._normal_interval()

    def tick(self) -> bool:
        if not self.enabled:
            return False
        if SEMVER_RE.fullmatch(self.version) is None or self.version.endswith("-local"):
            return False

        with self._lock:
            now = float(self.now_epoch())
            if not self._due(now):
                return False

            self._state["last_attempt_epoch"] = now
            self._save_state()
            try:
                status = self.transport.request(
                    method="POST",
                    path="/v1/heartbeat",
                    payload=self.payload(),
                    token=self.installation_token,
                    timeout_seconds=HTTP_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                self.log.warning(
                    "Telemetry heartbeat failed; will retry later: %s",
                    exc,
                )
                return False

            if not 200 <= int(status) < 300:
                self.log.warning(
                    "Telemetry heartbeat failed with HTTP %s; will retry later",
                    status,
                )
                return False

            self._state["last_success_epoch"] = now
            self._state["last_reported_version"] = self.version
            self._save_state()
            return True

    def delete(self) -> bool:
        with self._lock:
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
                self.log.warning(
                    "Telemetry deletion failed with HTTP %s",
                    status,
                )
                return False

            self._state.pop("last_success_epoch", None)
            self._state.pop("last_reported_version", None)
            self._state.pop("last_attempt_epoch", None)
            self._save_state()
            return True


class TelemetryRunner:
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
            name="dh-internet-telemetry",
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
