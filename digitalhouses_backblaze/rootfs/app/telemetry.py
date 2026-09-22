"""Optional DigitalHouses product telemetry client."""

from __future__ import annotations

import json
import secrets
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

TELEMETRY_URL = "https://telemetry.digitalhouses.vip/v1/heartbeat"
STATE_FILE = Path("/data/telemetry_state.json")
PRODUCT = "digitalhouses_backblaze_app"
POLICY_VERSION = 1
SCHEMA_VERSION = 1
DAY_SECONDS = 24 * 60 * 60
JITTER_SECONDS = 30 * 60


def _load_state() -> dict[str, Any]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def _write_state(state: dict[str, Any]) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(state, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(STATE_FILE)


def ensure_identity() -> dict[str, Any]:
    state = _load_state()
    changed = False
    if not state.get("installation_id"):
        state["installation_id"] = str(uuid.uuid4())
        changed = True
    if not state.get("installation_token"):
        state["installation_token"] = secrets.token_hex(32)
        changed = True
    if changed:
        _write_state(state)
    return state


def heartbeat_if_due(version: str, *, timeout_seconds: int = 5) -> bool:
    state = ensure_identity()
    now = int(time.time())
    due = int(state.get("next_heartbeat_at") or 0)
    last_version = str(state.get("last_success_version") or "")
    if due > now and last_version == version:
        return False

    payload = {
        "schema": SCHEMA_VERSION,
        "telemetry_policy_version": POLICY_VERSION,
        "installation_id": state["installation_id"],
        "product": PRODUCT,
        "version": version,
    }
    request = urllib.request.Request(
        TELEMETRY_URL,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {state['installation_token']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if response.status not in {200, 204}:
                return False
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        state["next_heartbeat_at"] = now + 6 * 60 * 60
        _write_state(state)
        return False

    jitter = secrets.randbelow(2 * JITTER_SECONDS + 1) - JITTER_SECONDS
    state["last_success_version"] = version
    state["next_heartbeat_at"] = now + DAY_SECONDS + jitter
    _write_state(state)
    return True
