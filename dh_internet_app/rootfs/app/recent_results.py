"""Persisted recent successful Speedtest results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from state import atomic_write_json, iso, now_local

RECENT_RESULTS_LIMIT = 20


def default_recent_results() -> dict[str, Any]:
    return {"results": [], "updated_at": None}


def load_recent_results(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default_recent_results()
    if not isinstance(raw, dict):
        return default_recent_results()
    rows = raw.get("results")
    if not isinstance(rows, list):
        rows = []
    rows = [row for row in rows if isinstance(row, dict)]
    updated_at = raw.get("updated_at")
    if not isinstance(updated_at, str):
        updated_at = None
    return {
        "results": rows[:RECENT_RESULTS_LIMIT],
        "updated_at": updated_at,
    }


def save_recent_results(path: Path, store: dict[str, Any]) -> None:
    atomic_write_json(path, store)


def build_recent_record(
    speedtest: dict[str, Any],
    thresholds: dict[str, int | float],
    performance: dict[str, Any],
) -> dict[str, Any]:
    return {
        "tested_at": speedtest.get("tested_at"),
        "download_mbps": speedtest.get("download_mbps"),
        "upload_mbps": speedtest.get("upload_mbps"),
        "ping_ms": speedtest.get("ping_ms"),
        "jitter_ms": speedtest.get("jitter_ms"),
        "packet_loss_pct": speedtest.get("packet_loss_pct"),
        "provider": speedtest.get("provider"),
        "server": speedtest.get("server"),
        "result_url": speedtest.get("result_url"),
        "minimum_download_mbps": thresholds["minimum_download_mbps"],
        "minimum_upload_mbps": thresholds["minimum_upload_mbps"],
        "maximum_ping_ms": thresholds["maximum_ping_ms"],
        "low_download": bool(performance.get("low_download")),
        "low_upload": bool(performance.get("low_upload")),
        "high_ping": bool(performance.get("high_ping")),
        "performance_problem": bool(performance.get("performance_problem")),
    }


def append_recent_result(
    store: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    rows = list(store.get("results") or [])
    result_url = record.get("result_url")
    tested_at = record.get("tested_at")
    rows = [
        row
        for row in rows
        if not (
            (result_url and row.get("result_url") == result_url)
            or (not result_url and tested_at and row.get("tested_at") == tested_at)
        )
    ]
    rows.insert(0, dict(record))
    return {
        "results": rows[:RECENT_RESULTS_LIMIT],
        "updated_at": iso(now_local()),
    }


def recent_results_payload(store: dict[str, Any]) -> dict[str, Any]:
    rows = list(store.get("results") or [])[:RECENT_RESULTS_LIMIT]
    return {
        "count": len(rows),
        "limit": RECENT_RESULTS_LIMIT,
        "updated_at": store.get("updated_at"),
        "results": rows,
    }
