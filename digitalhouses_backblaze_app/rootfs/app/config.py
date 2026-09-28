from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OPTIONS_PATH = Path("/data/options.json")


@dataclass(frozen=True)
class AppConfig:
    application_key_id: str
    application_key: str
    refresh_interval_hours: int
    telemetry_enabled: bool
    log_level: str


def _required_non_empty_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required and must be a non-empty string")
    return value.strip()


def parse_config(raw: dict[str, Any]) -> AppConfig:
    application_key_id = _required_non_empty_string(raw, "application_key_id")
    application_key = _required_non_empty_string(raw, "application_key")

    refresh_interval_hours = raw.get("refresh_interval_hours", 6)
    if (
        isinstance(refresh_interval_hours, bool)
        or not isinstance(refresh_interval_hours, int)
    ):
        raise ValueError("refresh_interval_hours must be an integer")
    if not 1 <= refresh_interval_hours <= 168:
        raise ValueError("refresh_interval_hours must be between 1 and 168")

    telemetry_enabled = raw.get("telemetry_enabled", False)
    if not isinstance(telemetry_enabled, bool):
        raise ValueError("telemetry_enabled must be boolean")

    log_level = raw.get("log_level", "info")
    if not isinstance(log_level, str):
        raise ValueError("log_level must be a string")
    log_level = log_level.strip().lower()
    if log_level not in {"debug", "info", "warning", "error"}:
        raise ValueError("unsupported log_level")

    return AppConfig(
        application_key_id=application_key_id,
        application_key=application_key,
        refresh_interval_hours=refresh_interval_hours,
        telemetry_enabled=telemetry_enabled,
        log_level=log_level,
    )


def load_config(path: Path = OPTIONS_PATH) -> AppConfig:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("options.json must contain an object")
    return parse_config(raw)
