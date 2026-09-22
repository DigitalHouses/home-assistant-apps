"""Configuration loading for DigitalHouses Backblaze."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OPTIONS_FILE = Path("/data/options.json")


@dataclass(frozen=True)
class Settings:
    application_key_id: str
    application_key: str
    refresh_interval_hours: int
    telemetry_enabled: bool
    log_level: str


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def load_settings(path: Path = OPTIONS_FILE) -> Settings:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    level = str(raw.get("log_level", "info")).lower()
    if level not in {"debug", "info", "warning", "error"}:
        level = "info"

    return Settings(
        application_key_id=str(raw.get("application_key_id", "")).strip(),
        application_key=str(raw.get("application_key", "")).strip(),
        refresh_interval_hours=_bounded_int(
            raw.get("refresh_interval_hours"), 1, 24, 6
        ),
        telemetry_enabled=bool(raw.get("telemetry_enabled", False)),
        log_level=level,
    )
