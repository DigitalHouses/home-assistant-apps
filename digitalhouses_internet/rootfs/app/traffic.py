"""Persistent traffic accounting from Home Assistant cumulative counters."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from state import atomic_write_json, iso, month_key, now_local

HISTORY_MONTHS = 12
GIB = 1024 ** 3

_UNIT_MULTIPLIERS: dict[str, float] = {
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "kb": 1000,
    "kib": 1024,
    "mb": 1000 ** 2,
    "mib": 1024 ** 2,
    "gb": 1000 ** 3,
    "gib": 1024 ** 3,
    "tb": 1000 ** 4,
    "tib": 1024 ** 4,
}


def entity_total_bytes(payload: dict[str, Any]) -> int:
    state = str(payload.get("state", "")).strip().lower()
    if state in {"", "unknown", "unavailable", "none"}:
        raise ValueError("traffic source state is unavailable")
    try:
        value = float(state)
    except ValueError as exc:
        raise ValueError(f"traffic source state is not numeric: {state!r}") from exc
    if value < 0:
        raise ValueError("traffic source state must not be negative")

    attributes = payload.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    unit = str(attributes.get("unit_of_measurement") or "B").strip().lower()
    multiplier = _UNIT_MULTIPLIERS.get(unit)
    if multiplier is None:
        raise ValueError(f"unsupported traffic unit: {unit!r}")
    return max(0, int(round(value * multiplier)))


def _empty_month() -> dict[str, int]:
    return {
        "download_bytes": 0,
        "upload_bytes": 0,
        "samples": 0,
        "counter_resets": 0,
    }


def default_traffic_state(
    download_entity_id: str,
    upload_entity_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": {
            "download_entity_id": download_entity_id,
            "upload_entity_id": upload_entity_id,
        },
        "last": {
            "download_bytes": None,
            "upload_bytes": None,
            "observed_at": None,
        },
        "total": {
            "download_bytes": 0,
            "upload_bytes": 0,
        },
        "months": {},
        "counter_resets": 0,
        "source_changes": 0,
        "updated_at": None,
    }


def load_traffic_state(
    path: Path,
    download_entity_id: str,
    upload_entity_id: str,
) -> dict[str, Any]:
    expected = default_traffic_state(download_entity_id, upload_entity_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return expected
    if not isinstance(raw, dict):
        return expected

    total = raw.get("total")
    months = raw.get("months")
    last = raw.get("last")
    source = raw.get("source")
    if not isinstance(total, dict):
        total = {}
    if not isinstance(months, dict):
        months = {}
    if not isinstance(last, dict):
        last = {}
    if not isinstance(source, dict):
        source = {}

    result = default_traffic_state(download_entity_id, upload_entity_id)
    result["total"] = {
        "download_bytes": max(0, int(total.get("download_bytes") or 0)),
        "upload_bytes": max(0, int(total.get("upload_bytes") or 0)),
    }
    result["months"] = {
        str(key): {
            "download_bytes": max(0, int(value.get("download_bytes") or 0)),
            "upload_bytes": max(0, int(value.get("upload_bytes") or 0)),
            "samples": max(0, int(value.get("samples") or 0)),
            "counter_resets": max(0, int(value.get("counter_resets") or 0)),
        }
        for key, value in months.items()
        if isinstance(value, dict)
    }
    result["counter_resets"] = max(0, int(raw.get("counter_resets") or 0))
    result["source_changes"] = max(0, int(raw.get("source_changes") or 0))
    result["updated_at"] = raw.get("updated_at")

    same_source = (
        source.get("download_entity_id") == download_entity_id
        and source.get("upload_entity_id") == upload_entity_id
    )
    if same_source:
        result["last"] = {
            "download_bytes": last.get("download_bytes"),
            "upload_bytes": last.get("upload_bytes"),
            "observed_at": last.get("observed_at"),
        }
    else:
        result["source_changes"] += 1
    _trim_months(result)
    return result


def _trim_months(state: dict[str, Any]) -> None:
    months = state["months"]
    keep = sorted(months)[-HISTORY_MONTHS:]
    state["months"] = {key: months[key] for key in keep}


def _delta(current: int, previous: Any) -> tuple[int, bool]:
    if previous is None:
        return 0, False
    previous_int = max(0, int(previous))
    if current >= previous_int:
        return current - previous_int, False
    # Same source counter restarted. The current value is traffic accumulated
    # since the reset; traffic between the last observation and reset is unknowable.
    return current, True


def update_traffic(
    state: dict[str, Any],
    download_bytes: int,
    upload_bytes: int,
    *,
    when: datetime | None = None,
) -> dict[str, Any]:
    when = when or now_local()
    current_month = month_key(when)
    months = state["months"]
    if current_month not in months:
        months[current_month] = _empty_month()

    download_delta, download_reset = _delta(
        download_bytes, state["last"].get("download_bytes")
    )
    upload_delta, upload_reset = _delta(
        upload_bytes, state["last"].get("upload_bytes")
    )
    reset = download_reset or upload_reset

    state["total"]["download_bytes"] += download_delta
    state["total"]["upload_bytes"] += upload_delta
    months[current_month]["download_bytes"] += download_delta
    months[current_month]["upload_bytes"] += upload_delta
    months[current_month]["samples"] += 1
    if reset:
        months[current_month]["counter_resets"] += 1
        state["counter_resets"] += 1

    state["last"] = {
        "download_bytes": download_bytes,
        "upload_bytes": upload_bytes,
        "observed_at": iso(when),
    }
    state["updated_at"] = iso(when)
    _trim_months(state)
    return state


def save_traffic_state(path: Path, state: dict[str, Any]) -> None:
    atomic_write_json(path, state)


def _gib(value: int) -> float:
    return round(max(0, int(value)) / GIB, 3)


def traffic_payload(state: dict[str, Any], *, when: datetime | None = None) -> dict[str, Any]:
    when = when or now_local()
    current_month = month_key(when)
    month = state["months"].get(current_month) or _empty_month()
    history = []
    for key in sorted(state["months"])[-HISTORY_MONTHS:]:
        item = state["months"][key]
        download = int(item.get("download_bytes") or 0)
        upload = int(item.get("upload_bytes") or 0)
        history.append(
            {
                "month": key,
                "download_gib": _gib(download),
                "upload_gib": _gib(upload),
                "total_gib": _gib(download + upload),
                "samples": int(item.get("samples") or 0),
                "counter_resets": int(item.get("counter_resets") or 0),
            }
        )

    return {
        "download_total_gib": _gib(state["total"]["download_bytes"]),
        "upload_total_gib": _gib(state["total"]["upload_bytes"]),
        "download_month_gib": _gib(month.get("download_bytes", 0)),
        "upload_month_gib": _gib(month.get("upload_bytes", 0)),
        "history_count": len(history),
        "history": history,
        "month": current_month,
        "updated_at": state.get("updated_at"),
        "counter_resets": int(state.get("counter_resets") or 0),
        "source_changes": int(state.get("source_changes") or 0),
        "source": dict(state.get("source") or {}),
    }
