"""DigitalHouses Network App telemetry wire v1 / opt-in policy v1.

This worker is independent of MQTT, Go discovery, and the Ingress UI.
The optional worker is never started by the launcher without explicit
Home Assistant App consent; core network discovery remains operational.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Callable

PRODUCT = "digitalhouses_network_app"
ENDPOINT = "https://telemetry.digitalhouses.vip"
STATE_FILE = Path("/data/telemetry.json")
POLICY_VERSION = 1
SCHEMA = 1
NORMAL_INTERVAL = 24 * 3600
JITTER = 30 * 60
RETRY_INTERVAL = 3600
REQUEST_TIMEOUT = 5
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[A-Za-z0-9.-]+)?$")
LOG = logging.getLogger("dh_network_app.telemetry")


class TelemetryStateError(ValueError):
    """Refuse to overwrite a corrupted persistent installation identity."""


class HttpTransport:
    def request(self, method: str, path: str, payload: dict, token: str) -> int:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            ENDPOINT + path,
            data=body,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": "Bearer " + token,
                "User-Agent": "DigitalHouses-Telemetry/1",
            },
        )
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return int(response.status)


class TelemetryClient:
    def __init__(
        self,
        version: str,
        *,
        enabled: bool,
        state_file: Path = STATE_FILE,
        transport=None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.version = version
        self.enabled = enabled
        self.state_file = Path(state_file)
        self.transport = transport if transport is not None else HttpTransport()
        self.now = now
        self._lock = threading.Lock()
        # No installation identifier and no network activity before acceptance.
        self.state = self._load_or_create() if enabled else None

    def _load_or_create(self) -> dict:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError, OSError) as exc:
                raise TelemetryStateError("Invalid persistent telemetry JSON") from exc
            if not isinstance(data, dict) or data.get("schema_version") != 1:
                raise TelemetryStateError("Invalid telemetry state schema")
            ident = data.get("installation_id")
            try:
                parsed = uuid.UUID(str(ident))
                valid_uuid = parsed.version == 4 and str(parsed) == ident
            except (ValueError, TypeError, AttributeError):
                valid_uuid = False
            if not valid_uuid:
                raise TelemetryStateError("Invalid existing installation ID")
            token = data.get("installation_token")
            if not isinstance(token, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2}){32,}", token):
                raise TelemetryStateError("Invalid existing installation token")
            for key in ("last_attempt", "last_success"):
                value = data.get(key)
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                    raise TelemetryStateError("Invalid telemetry scheduler field " + key)
            reported = data.get("last_version")
            if reported is not None and (not isinstance(reported, str) or not reported):
                raise TelemetryStateError("Invalid reported version")
            return data
        data = {
            "schema_version": 1,
            "installation_id": str(uuid.uuid4()),
            "installation_token": secrets.token_hex(32),
        }
        self._save(data)
        return data

    def _save(self, data: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replacement; never put a credential on stdout or in exception logs.
        fd, temp_path = tempfile.mkstemp(prefix=".telemetry-", dir=self.state_file.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                os.fchmod(target.fileno(), 0o600)
                json.dump(data, target, separators=(",", ":"), sort_keys=True)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temp_path, self.state_file)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def payload(self) -> dict:
        if self.state is None:
            raise TelemetryStateError("Telemetry consent is not granted")
        return {
            "schema": SCHEMA,
            "telemetry_policy_version": POLICY_VERSION,
            "installation_id": self.state["installation_id"],
            "product": PRODUCT,
            "version": self.version,
        }

    def _interval(self) -> int:
        digest = hashlib.sha256(self.state["installation_id"].encode("ascii")).digest()
        jitter = int.from_bytes(digest[:4], "big") % (2 * JITTER + 1) - JITTER
        return NORMAL_INTERVAL + jitter

    def _due(self, current: float) -> bool:
        last_attempt = self.state.get("last_attempt")
        last_success = self.state.get("last_success")
        if last_attempt is not None and (last_success is None or last_attempt > last_success):
            if current - last_attempt < RETRY_INTERVAL:
                return False
        if last_success is None or self.state.get("last_version") != self.version:
            return True
        return current - last_success >= self._interval()

    def tick(self) -> bool:
        if self.state is None or SEMVER.fullmatch(self.version) is None or self.version.endswith("-local"):
            return False
        with self._lock:
            current = float(self.now())
            if not self._due(current):
                return False
            self.state["last_attempt"] = current
            self._save(self.state)
            try:
                status = self.transport.request(
                    "POST", "/v1/heartbeat", self.payload(), self.state["installation_token"]
                )
            except Exception as exc:
                LOG.warning("Telemetry heartbeat failed; will retry later: %s", exc.__class__.__name__)
                return False
            if not 200 <= status < 300:
                LOG.warning("Telemetry heartbeat failed (HTTP %s)", status)
                return False
            self.state["last_success"] = current
            self.state["last_version"] = self.version
            self._save(self.state)
            LOG.info("Telemetry heartbeat accepted: product=%s version=%s", PRODUCT, self.version)
            return True

    def delete_installation(self) -> bool:
        """Delete remotely using this installation's secret; rotate local ID on success."""
        if self.state is None:
            return False
        with self._lock:
            try:
                status = self.transport.request(
                    "DELETE",
                    "/v1/installation",
                    {
                        "schema": 1,
                        "installation_id": self.state["installation_id"],
                        "product": PRODUCT,
                    },
                    self.state["installation_token"],
                )
            except Exception as exc:
                LOG.warning("Telemetry deletion failed: %s", exc.__class__.__name__)
                return False
            if not (200 <= status < 300 or status == 404):
                LOG.warning("Telemetry deletion failed (HTTP %s)", status)
                return False
            fresh = {
                "schema_version": 1,
                "installation_id": str(uuid.uuid4()),
                "installation_token": secrets.token_hex(32),
            }
            self._save(fresh)
            self.state = fresh
            return True


def run_forever() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if os.environ.get("DH_TELEMETRY_ENABLED") != "true":
        LOG.info("Optional telemetry is disabled; no heartbeat will be sent")
        return
    try:
        client = TelemetryClient(os.environ["APP_VERSION"], enabled=True)
    except (TelemetryStateError, OSError) as exc:
        LOG.error("Telemetry state unavailable; core network discovery unaffected: %s", exc)
        return
    while True:
        try:
            client.tick()
        except (OSError, ValueError) as exc:
            LOG.warning("Telemetry scheduler failed; retry later: %s", exc.__class__.__name__)
        time.sleep(60)


if __name__ == "__main__":
    # Explicitly requested, authenticated erasure is available from the App
    # container even after telemetry was disabled in Supervisor options.
    import sys
    if len(sys.argv) == 2 and sys.argv[1] == "--delete":
        if not STATE_FILE.exists():
            print("No registered telemetry installation")
            raise SystemExit(0)
        client = TelemetryClient(os.environ["APP_VERSION"], enabled=True)
        raise SystemExit(0 if client.delete_installation() else 1)
    if len(sys.argv) != 1:
        raise SystemExit("Usage: telemetry.py [--delete]")
    run_forever()
