"""Persistent traffic accounting from Home Assistant cumulative counters."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from state import (
    ContractDataError,
    atomic_write_json,
    iso,
    load_json_object,
    month_key,
    now_local,
)

HISTORY_MONTHS = 12
GIB = 1024 ** 3

_SIZE_TO_BYTES: dict[str, float] = {
    "bit": 1.0 / 8.0,
    "kbit": 1000.0 / 8.0,
    "Mbit": 1000.0**2 / 8.0,
    "Gbit": 1000.0**3 / 8.0,
    "B": 1.0,
    "kB": 1000.0,
    "MB": 1000.0**2,
    "GB": 1000.0**3,
    "TB": 1000.0**4,
    "PB": 1000.0**5,
    "KiB": 1024.0,
    "MiB": 1024.0**2,
    "GiB": 1024.0**3,
    "TiB": 1024.0**4,
    "PiB": 1024.0**5,
}

_SIZE_ALIASES_TO_BYTES: dict[str, float] = {
    "byte": 1.0,
    "bytes": 1.0,
    "b": 1.0 / 8.0,
    "kb": 1000.0 / 8.0,
    "mb": 1000.0**2 / 8.0,
    "gb": 1000.0**3 / 8.0,
    "kib": 1024.0,
    "mib": 1024.0**2,
    "gib": 1024.0**3,
    "tib": 1024.0**4,
    "pib": 1024.0**5,
}


def _size_multiplier(unit: str) -> float | None:
    multiplier = _SIZE_TO_BYTES.get(unit)
    if multiplier is not None:
        return multiplier
    return _SIZE_ALIASES_TO_BYTES.get(unit.lower())


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
        raise ValueError("traffic source attributes must be an object")
    unit = attributes.get("unit_of_measurement")
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("traffic source unit_of_measurement is required")
    unit = unit.strip()
    multiplier = _size_multiplier(unit)
    if multiplier is None:
        raise ValueError(f"unsupported traffic unit: {unit!r}")
    return max(0, int(round(value * multiplier)))


_RATE_TO_MBIT: dict[str, float] = {
    "bit/s": 1.0 / 1_000_000.0,
    "kbit/s": 1.0 / 1_000.0,
    "Mbit/s": 1.0,
    "Gbit/s": 1_000.0,
    "B/s": 8.0 / 1_000_000.0,
    "kB/s": 8.0 / 1_000.0,
    "MB/s": 8.0,
    "GB/s": 8_000.0,
    "KiB/s": (1024.0 * 8.0) / 1_000_000.0,
    "MiB/s": (1024.0**2 * 8.0) / 1_000_000.0,
    "GiB/s": (1024.0**3 * 8.0) / 1_000_000.0,
}

_RATE_ALIASES_TO_MBIT: dict[str, float] = {
    "bps": 1.0 / 1_000_000.0,
    "kbps": 1.0 / 1_000.0,
    "mbps": 1.0,
    "gbps": 1_000.0,
    "b/s": 1.0 / 1_000_000.0,
    "kb/s": 1.0 / 1_000.0,
    "mb/s": 1.0,
    "gb/s": 1_000.0,
}


def _rate_multiplier(unit: str) -> float | None:
    multiplier = _RATE_TO_MBIT.get(unit)
    if multiplier is not None:
        return multiplier
    return _RATE_ALIASES_TO_MBIT.get(unit.lower())


def entity_rate_mbps(payload: dict[str, Any]) -> float:
    state = str(payload.get("state", "")).strip().lower()
    if state in {"", "unknown", "unavailable", "none"}:
        raise ValueError("rate source state is unavailable")
    try:
        value = float(state)
    except ValueError as exc:
        raise ValueError(f"rate source state is not numeric: {state!r}") from exc
    if value < 0:
        raise ValueError("rate source state must not be negative")
    attributes = payload.get("attributes")
    if not isinstance(attributes, dict):
        raise ValueError("rate source attributes must be an object")
    unit = attributes.get("unit_of_measurement")
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("rate source unit_of_measurement is required")
    unit = unit.strip()
    multiplier = _rate_multiplier(unit)
    if multiplier is None:
        raise ValueError(f"unsupported router rate unit: {unit!r}")
    return round(value * multiplier, 6)


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


def _required_nonnegative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractDataError(f"{field} must be a non-negative integer")
    return value


def _optional_nonnegative_int(value: Any, *, field: str) -> int | None:
    if value is None:
        return None
    return _required_nonnegative_int(value, field=field)


def _optional_timestamp(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ContractDataError(f"{field} must be an ISO-8601 string or null")
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContractDataError(f"{field} must be valid ISO-8601") from exc
    return value


def load_traffic_state(
    path: Path,
    download_entity_id: str,
    upload_entity_id: str,
) -> dict[str, Any]:
    raw = load_json_object(path, label="traffic")
    if raw is None:
        return default_traffic_state(download_entity_id, upload_entity_id)
    if raw.get("schema_version") != 1:
        raise ContractDataError("traffic.schema_version must be 1")

    source = raw.get("source")
    last = raw.get("last")
    total = raw.get("total")
    months = raw.get("months")
    if not isinstance(source, dict):
        raise ContractDataError("traffic.source must be an object")
    if not isinstance(last, dict):
        raise ContractDataError("traffic.last must be an object")
    if not isinstance(total, dict):
        raise ContractDataError("traffic.total must be an object")
    if not isinstance(months, dict):
        raise ContractDataError("traffic.months must be an object")

    for field in ("download_entity_id", "upload_entity_id"):
        if not isinstance(source.get(field), str):
            raise ContractDataError(f"traffic.source.{field} must be a string")

    result = default_traffic_state(download_entity_id, upload_entity_id)
    result["total"] = {
        "download_bytes": _required_nonnegative_int(
            total.get("download_bytes"),
            field="traffic.total.download_bytes",
        ),
        "upload_bytes": _required_nonnegative_int(
            total.get("upload_bytes"),
            field="traffic.total.upload_bytes",
        ),
    }

    validated_months: dict[str, dict[str, int]] = {}
    for key, value in months.items():
        if not isinstance(key, str) or not key:
            raise ContractDataError("traffic.months keys must be non-empty strings")
        if not isinstance(value, dict):
            raise ContractDataError(f"traffic.months.{key} must be an object")
        validated_months[key] = {
            "download_bytes": _required_nonnegative_int(
                value.get("download_bytes"),
                field=f"traffic.months.{key}.download_bytes",
            ),
            "upload_bytes": _required_nonnegative_int(
                value.get("upload_bytes"),
                field=f"traffic.months.{key}.upload_bytes",
            ),
            "samples": _required_nonnegative_int(
                value.get("samples"),
                field=f"traffic.months.{key}.samples",
            ),
            "counter_resets": _required_nonnegative_int(
                value.get("counter_resets"),
                field=f"traffic.months.{key}.counter_resets",
            ),
        }
    result["months"] = validated_months
    result["counter_resets"] = _required_nonnegative_int(
        raw.get("counter_resets"),
        field="traffic.counter_resets",
    )
    result["source_changes"] = _required_nonnegative_int(
        raw.get("source_changes"),
        field="traffic.source_changes",
    )
    result["updated_at"] = _optional_timestamp(
        raw.get("updated_at"),
        field="traffic.updated_at",
    )

    last_download = _optional_nonnegative_int(
        last.get("download_bytes"),
        field="traffic.last.download_bytes",
    )
    last_upload = _optional_nonnegative_int(
        last.get("upload_bytes"),
        field="traffic.last.upload_bytes",
    )
    observed_at = _optional_timestamp(
        last.get("observed_at"),
        field="traffic.last.observed_at",
    )
    if (last_download is None) != (last_upload is None):
        raise ContractDataError(
            "traffic.last download/upload counters must both be null or both be integers"
        )
    if last_download is None and observed_at is not None:
        raise ContractDataError(
            "traffic.last.observed_at must be null when counters are null"
        )
    if last_download is not None and observed_at is None:
        raise ContractDataError(
            "traffic.last.observed_at is required when counters are present"
        )

    same_source = (
        source["download_entity_id"] == download_entity_id
        and source["upload_entity_id"] == upload_entity_id
    )
    if same_source:
        result["last"] = {
            "download_bytes": last_download,
            "upload_bytes": last_upload,
            "observed_at": observed_at,
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
    previous_int = _required_nonnegative_int(
        previous,
        field="traffic.last counter",
    )
    if current >= previous_int:
        return current - previous_int, False
    # Same source counter restarted. The current value is traffic accumulated
    # since the reset; traffic between the last observation and reset is unknowable.
    return current, True


def _observed_month(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ContractDataError("traffic.last.observed_at must be ISO-8601 or null")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContractDataError(
            "traffic.last.observed_at must be valid ISO-8601"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=now_local().tzinfo)
    return month_key(parsed)


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

    previous_month = _observed_month(state["last"].get("observed_at"))
    if previous_month is not None and previous_month != current_month:
        # Cumulative counters cannot tell how a cross-midnight delta splits
        # between months. The first sample of a new month is a fresh baseline.
        download_delta, download_reset = 0, False
        upload_delta, upload_reset = 0, False
    else:
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
    for key in sorted(state["months"], reverse=True)[:HISTORY_MONTHS]:
        item = state["months"][key]
        download = item["download_bytes"]
        upload = item["upload_bytes"]
        history.append(
            {
                "month": key,
                "download_gib": _gib(download),
                "upload_gib": _gib(upload),
                "total_gib": _gib(download + upload),
                "samples": item["samples"],
                "counter_resets": item["counter_resets"],
            }
        )

    return {
        "download_total_gib": _gib(state["total"]["download_bytes"]),
        "upload_total_gib": _gib(state["total"]["upload_bytes"]),
        "download_month_gib": _gib(month["download_bytes"]),
        "upload_month_gib": _gib(month["upload_bytes"]),
        "history_count": len(history),
        "history": history,
        "month": current_month,
        "updated_at": state.get("updated_at"),
        "counter_resets": state["counter_resets"],
        "source_changes": state["source_changes"],
        "source": dict(state["source"]),
    }
