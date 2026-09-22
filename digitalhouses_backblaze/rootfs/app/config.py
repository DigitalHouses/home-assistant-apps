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
    log_level: str


def parse_config(raw: dict[str, Any]) -> AppConfig:
    application_key_id = str(raw.get("application_key_id") or "").strip()
    application_key = str(raw.get("application_key") or "").strip()
    if not application_key_id:
        raise ValueError("application_key_id is required")
    if not application_key:
        raise ValueError("application_key is required")

    refresh_interval_hours = int(raw.get("refresh_interval_hours", 6))
    if not 1 <= refresh_interval_hours <= 168:
        raise ValueError("refresh_interval_hours must be between 1 and 168")

    log_level = str(raw.get("log_level") or "info").strip().lower()
    if log_level not in {"debug", "info", "warning", "error"}:
        raise ValueError("unsupported log_level")

    return AppConfig(
        application_key_id=application_key_id,
        application_key=application_key,
        refresh_interval_hours=refresh_interval_hours,
        log_level=log_level,
    )


def load_config(path: Path = OPTIONS_PATH) -> AppConfig:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("options.json must contain an object")
    return parse_config(raw)
