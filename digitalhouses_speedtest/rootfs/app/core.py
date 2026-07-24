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
    "Готово": "Ready",
    "Измерение": "Running",
    "Успешно": "Success",
    "Ошибка": "Error",
    "Нет соединения": "No connectivity",
    "Отключено": "Ready",
}

DEFAULT_THRESHOLDS: dict[str, float] = {
    "minimum_download_mbps": 10.0,
    "minimum_upload_mbps": 10.0,
    "maximum_ping_ms": 200.0,
}


def utc_now() -> str:
    """Return a compact UTC timestamp accepted by Home Assistant."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compact_number(value: float) -> int | float:
    return int(value) if value.is_integer() else round(value, 3)


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


def update_runtime_status(
    state: dict[str, Any],
    status: str,
    attempted_at: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Change runtime status without replacing the last successful measurements."""
    updated = migrate_state(state)
    updated["status"] = status if status in VALID_STATUSES else "Error"
    if attempted_at is not None:
        updated["last_attempt"] = attempted_at
    updated["error"] = error
    return updated


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
        numeric = _as_float(value)
        if numeric is None:
            return None
        return round(numeric * 8 / 1_000_000, 3)

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
        "ping_ms": _as_float(ping.get("latency")),
        "jitter_ms": _as_float(ping.get("jitter")),
        # A missing Ookla value must remain null/unknown, never 0%.
        "packet_loss": _as_float(raw.get("packetLoss")),
        "provider": raw.get("isp"),
        "external_ip": interface.get("externalIp"),
        "server": server_text,
        "server_id": str(server_id) if server_id is not None else None,
        "result_url": result.get("url"),
        "last_success": raw.get("timestamp") or attempted_at,
        "last_attempt": attempted_at,
        "error": None,
    }


def normalize_thresholds(raw: Any) -> dict[str, int | float]:
    """Validate persisted threshold values and apply safe defaults."""
    source = raw if isinstance(raw, dict) else {}
    specs = {
        "minimum_download_mbps": (1.0, 10_000.0),
        "minimum_upload_mbps": (1.0, 10_000.0),
        "maximum_ping_ms": (1.0, 1_000.0),
    }
    normalized: dict[str, int | float] = {}
    for key, (minimum, maximum) in specs.items():
        value = _as_float(source.get(key))
        if value is None or not minimum <= value <= maximum:
            value = DEFAULT_THRESHOLDS[key]
        normalized[key] = _compact_number(value)
    return normalized


def parse_timestamp(value: Any) -> datetime | None:
    """Parse a Home Assistant/Ookla timestamp into an aware UTC datetime."""
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def is_result_fresh(
    last_success: Any,
    expire_after_seconds: int,
    now: datetime | str | None = None,
) -> bool:
    """Return whether the last successful measurement is still current."""
    timestamp = parse_timestamp(last_success)
    if timestamp is None:
        return False
    if expire_after_seconds <= 0:
        return True

    if now is None:
        current = datetime.now(timezone.utc)
    elif isinstance(now, datetime):
        current = now
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
    else:
        current = parse_timestamp(now)
        if current is None:
            return False

    age = (current - timestamp).total_seconds()
    return age <= expire_after_seconds


def _server_id_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def evaluate_performance(
    state: dict[str, Any],
    thresholds: dict[str, Any],
    *,
    available: bool,
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    """Evaluate the last successful test against the current thresholds."""
    current = migrate_state(state)
    limits = normalize_thresholds(thresholds)
    evaluated = evaluated_at or utc_now()

    download = _as_float(current.get("download_mbps"))
    upload = _as_float(current.get("upload_mbps"))
    ping = _as_float(current.get("ping_ms"))
    values_present = download is not None and upload is not None and ping is not None
    effective_available = bool(available and values_present and current.get("last_success"))

    low_download = bool(
        download is not None and download < float(limits["minimum_download_mbps"])
    )
    low_upload = bool(
        upload is not None and upload < float(limits["minimum_upload_mbps"])
    )
    high_ping = bool(ping is not None and ping > float(limits["maximum_ping_ms"]))
    low_speed = low_download or low_upload
    performance_problem = low_speed or high_ping
    reasons = [
        reason
        for reason, active in (
            ("low_download", low_download),
            ("low_upload", low_upload),
            ("high_ping", high_ping),
        )
        if active
    ]

    common = {
        "evaluated_at": evaluated,
        "result_timestamp": current.get("last_success"),
        "server": current.get("server"),
        "server_id": _server_id_value(current.get("server_id")),
    }

    def metric(
        active: bool,
        current_value: float | None,
        threshold: int | float,
        unit: str,
        comparison: str,
    ) -> dict[str, Any]:
        difference = (
            round(current_value - float(threshold), 3)
            if current_value is not None
            else None
        )
        return {
            "state": "ON" if active else "OFF",
            "attributes": {
                "current_value": current_value,
                "threshold": threshold,
                "unit": unit,
                "comparison": comparison,
                "difference": difference,
                **common,
            },
        }

    return {
        "available": effective_available,
        "evaluated_at": evaluated,
        "result_timestamp": current.get("last_success"),
        "low_download": metric(
            low_download,
            download,
            limits["minimum_download_mbps"],
            "Mbit/s",
            "less_than",
        ),
        "low_upload": metric(
            low_upload,
            upload,
            limits["minimum_upload_mbps"],
            "Mbit/s",
            "less_than",
        ),
        "high_ping": metric(
            high_ping,
            ping,
            limits["maximum_ping_ms"],
            "ms",
            "greater_than",
        ),
        "performance_problem": {
            "state": "ON" if performance_problem else "OFF",
            "attributes": {
                "low_download": low_download,
                "low_upload": low_upload,
                "high_ping": high_ping,
                "low_speed": low_speed,
                "problem_reasons": reasons,
                **common,
            },
        },
    }


def build_recent_record(
    state: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    """Build an immutable history entry from a successful test."""
    limits = normalize_thresholds(thresholds)
    evaluation = evaluate_performance(
        state,
        limits,
        available=True,
        evaluated_at=state.get("last_success") or utc_now(),
    )
    aggregate = evaluation["performance_problem"]["attributes"]
    return {
        "timestamp": state.get("last_success"),
        "server": state.get("server"),
        "server_id": _server_id_value(state.get("server_id")),
        "download_mbps": _as_float(state.get("download_mbps")),
        "upload_mbps": _as_float(state.get("upload_mbps")),
        "ping_ms": _as_float(state.get("ping_ms")),
        "jitter_ms": _as_float(state.get("jitter_ms")),
        "packet_loss": _as_float(state.get("packet_loss")),
        "result_url": state.get("result_url"),
        "minimum_download_mbps": limits["minimum_download_mbps"],
        "minimum_upload_mbps": limits["minimum_upload_mbps"],
        "maximum_ping_ms": limits["maximum_ping_ms"],
        "low_download": evaluation["low_download"]["state"] == "ON",
        "low_upload": evaluation["low_upload"]["state"] == "ON",
        "high_ping": evaluation["high_ping"]["state"] == "ON",
        "low_speed": aggregate["low_speed"],
        "performance_problem": evaluation["performance_problem"]["state"] == "ON",
        "problem_reasons": list(aggregate["problem_reasons"]),
    }


def default_recent_results() -> dict[str, Any]:
    return {"schema_version": 1, "updated_at": None, "results": []}


def migrate_recent_results(raw: Any, limit: int) -> dict[str, Any]:
    """Load only valid 1.1 history; no 1.0 state is backfilled."""
    store = default_recent_results()
    if not isinstance(raw, dict):
        return store
    results = raw.get("results")
    if not isinstance(results, list):
        return store
    valid = [item for item in results if isinstance(item, dict)]
    store["updated_at"] = raw.get("updated_at")
    store["results"] = valid[:limit]
    return store


def _recent_identity(record: dict[str, Any]) -> tuple[Any, ...]:
    if record.get("result_url"):
        return ("url", record.get("result_url"))
    return ("fallback", record.get("timestamp"), record.get("server_id"))


def append_recent_result(
    store: dict[str, Any],
    record: dict[str, Any],
    limit: int,
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """Insert newest-first, deduplicate, and enforce the configured limit."""
    current = migrate_recent_results(store, max(limit, 1))
    identity = _recent_identity(record)
    remaining = [
        item for item in current["results"] if _recent_identity(item) != identity
    ]
    current["results"] = [record, *remaining][:limit]
    current["updated_at"] = updated_at or utc_now()
    return current


def recent_results_payload(store: dict[str, Any], limit: int) -> dict[str, Any]:
    current = migrate_recent_results(store, limit)
    return {
        "updated_at": current.get("updated_at"),
        "count": len(current["results"]),
        "limit": limit,
        "results": current["results"],
    }
