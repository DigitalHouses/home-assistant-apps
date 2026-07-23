\
"""Pure helper functions for DigitalHouses Speedtest."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_STATUSES = {"Ready", "Running", "Success", "Error", "No connectivity"}
LEGACY_STATUS_MAP = {
    "\u0413\u043e\u0442\u043e\u0432\u043e": "Ready",
    "\u0418\u0437\u043c\u0435\u0440\u0435\u043d\u0438\u0435": "Running",
    "\u0423\u0441\u043f\u0435\u0448\u043d\u043e": "Success",
    "\u041e\u0448\u0438\u0431\u043a\u0430": "Error",
    "\u041d\u0435\u0442 \u0441\u043e\u0435\u0434\u0438\u043d\u0435\u043d\u0438\u044f": "No connectivity",
    "\u041e\u0442\u043a\u043b\u044e\u0447\u0435\u043d\u043e": "Ready",
}


def utc_now() -> str:
    """Return a compact UTC timestamp accepted by Home Assistant."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_state() -> dict[str, Any]:
    """Return an empty, valid application state."""
    return {
        "status": "Ready",
        "download_mbps": None,
        "upload_mbps": None,
        "ping_ms": None,
        "jitter_ms": None,
        "packet_loss": None,
        "provider": None,
        "external_ip": None,
        "server": None,
        "server_id": None,
        "result_url": None,
        "last_success": None,
        "last_attempt": None,
        "error": None,
    }


def migrate_state(raw: Any) -> dict[str, Any]:
    """Merge persisted state with defaults and translate legacy statuses."""
    state = default_state()
    if isinstance(raw, dict):
        for key in state:
            if key in raw:
                state[key] = raw[key]
    status = LEGACY_STATUS_MAP.get(str(state.get("status")), state.get("status"))
    state["status"] = status if status in VALID_STATUSES else "Ready"
    if state["status"] == "Running":
        state["status"] = "Ready"
    return state


def load_json(path: Path, default: Any) -> Any:
    """Load JSON without allowing a corrupt cache to stop the App."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def atomic_write_json(path: Path, payload: Any) -> None:
    """Atomically replace a JSON file in the same filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def parse_server_list(output: str) -> list[dict[str, Any]]:
    """Parse the human-readable table emitted by ``speedtest --servers``."""
    servers: list[dict[str, Any]] = []
    for line in output.splitlines():
        parts = re.split(r"\s{2,}", line.strip(), maxsplit=3)
        if len(parts) != 4 or not parts[0].isdigit():
            continue
        server_id, provider, location, country = parts
        servers.append(
            {
                "id": int(server_id),
                "provider": provider.strip(),
                "location": location.strip(),
                "country": country.strip(),
            }
        )
    return servers


def build_success_state(raw: dict[str, Any], attempted_at: str) -> dict[str, Any]:
    """Convert an Ookla JSON result into the retained MQTT state."""
    download = raw.get("download") or {}
    upload = raw.get("upload") or {}
    ping = raw.get("ping") or {}
    interface = raw.get("interface") or {}
    server = raw.get("server") or {}
    result = raw.get("result") or {}

    def mbps(value: Any) -> float | None:
        if value is None:
            return None
        return round(float(value) * 8 / 1_000_000, 3)

    server_location = [server.get("location"), server.get("country")]
    location_text = ", ".join(str(item) for item in server_location if item)
    server_text = " — ".join(
        str(item) for item in (server.get("name"), location_text) if item
    ) or None

    server_id = server.get("id")
    return {
        "status": "Success",
        "download_mbps": mbps(download.get("bandwidth")),
        "upload_mbps": mbps(upload.get("bandwidth")),
        "ping_ms": ping.get("latency"),
        "jitter_ms": ping.get("jitter"),
        "packet_loss": raw.get("packetLoss"),
        "provider": raw.get("isp"),
        "external_ip": interface.get("externalIp"),
        "server": server_text,
        "server_id": str(server_id) if server_id is not None else None,
        "result_url": result.get("url"),
        "last_success": raw.get("timestamp") or attempted_at,
        "last_attempt": attempted_at,
        "error": None,
    }
