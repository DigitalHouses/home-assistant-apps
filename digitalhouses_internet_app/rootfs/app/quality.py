"""Speedtest quality thresholds and problem evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from state import atomic_write_json, iso, now_local

DEFAULT_THRESHOLDS: dict[str, int | float] = {
    "minimum_download_mbps": 10,
    "minimum_upload_mbps": 10,
    "maximum_ping_ms": 200,
}

SPECS: dict[str, tuple[float, float]] = {
    "minimum_download_mbps": (1.0, 10_000.0),
    "minimum_upload_mbps": (1.0, 10_000.0),
    "maximum_ping_ms": (1.0, 1_000.0),
}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compact(value: float) -> int | float:
    return int(value) if value.is_integer() else round(value, 3)


def normalize_thresholds(raw: Any) -> dict[str, int | float]:
    source = raw if isinstance(raw, dict) else {}
    result: dict[str, int | float] = {}
    for key, (minimum, maximum) in SPECS.items():
        value = _number(source.get(key))
        if value is None or not minimum <= value <= maximum:
            value = float(DEFAULT_THRESHOLDS[key])
        result[key] = _compact(value)
    return result


def load_thresholds(path: Path) -> dict[str, int | float]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        raw = {}
    thresholds = normalize_thresholds(raw)
    atomic_write_json(path, thresholds)
    return thresholds


def set_threshold(
    thresholds: dict[str, int | float],
    key: str,
    raw_value: Any,
) -> dict[str, int | float]:
    if key not in SPECS:
        raise ValueError(f"unknown threshold: {key}")
    value = _number(raw_value)
    minimum, maximum = SPECS[key]
    if value is None or not minimum <= value <= maximum:
        raise ValueError(
            f"{key} must be between {minimum:g} and {maximum:g}"
        )
    updated = dict(thresholds)
    updated[key] = _compact(value)
    return updated


def evaluate_performance(
    speedtest: dict[str, Any],
    thresholds: dict[str, int | float],
) -> dict[str, Any]:
    limits = normalize_thresholds(thresholds)
    download = _number(speedtest.get("download_mbps"))
    upload = _number(speedtest.get("upload_mbps"))
    ping = _number(speedtest.get("ping_ms"))
    available = bool(
        speedtest.get("tested_at")
        and download is not None
        and upload is not None
        and ping is not None
    )

    low_download = bool(
        available and download < float(limits["minimum_download_mbps"])
    )
    low_upload = bool(
        available and upload < float(limits["minimum_upload_mbps"])
    )
    high_ping = bool(
        available and ping > float(limits["maximum_ping_ms"])
    )
    reasons = [
        reason
        for reason, active in (
            ("low_download", low_download),
            ("low_upload", low_upload),
            ("high_ping", high_ping),
        )
        if active
    ]
    return {
        "available": available,
        "low_download": low_download,
        "low_upload": low_upload,
        "high_ping": high_ping,
        "performance_problem": bool(reasons),
        "problem_reasons": reasons,
        "download_mbps": download,
        "upload_mbps": upload,
        "ping_ms": ping,
        "minimum_download_mbps": limits["minimum_download_mbps"],
        "minimum_upload_mbps": limits["minimum_upload_mbps"],
        "maximum_ping_ms": limits["maximum_ping_ms"],
        "result_timestamp": speedtest.get("tested_at"),
        "evaluated_at": iso(now_local()),
    }
