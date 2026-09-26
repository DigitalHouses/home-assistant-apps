from __future__ import annotations

import re
from datetime import datetime
from numbers import Real
from typing import Any, Mapping

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
)

EVENT_SCHEMA_VERSION = 2
EVENT_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "db_connection_lost": ("database_engine", "database_name"),
    "db_connection_restored": (
        "database_engine",
        "database_name",
        "outage_seconds",
    ),
    "recorder_writing_stopped": ("stale_threshold_seconds",),
    "recorder_writing_restored": ("stale_threshold_seconds",),
    "storage_usage_high": (
        "used_percent",
        "used_gb",
        "free_gb",
        "total_gb",
        "threshold_percent",
        "cause",
    ),
    "storage_usage_normal": (
        "used_percent",
        "used_gb",
        "free_gb",
        "total_gb",
        "threshold_percent",
        "cause",
    ),
}


def require_nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()


def validate_release_version(value: object) -> str:
    version = require_nonempty_string(value, "APP_VERSION")
    if SEMVER_RE.fullmatch(version) is None:
        raise ValueError("APP_VERSION must be a semantic release version")
    return version


def validate_timestamp(value: object, label: str) -> str:
    raw = require_nonempty_string(value, label)
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{label} must be ISO8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return raw


def _require_number(value: object, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be numeric")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must be >= {minimum:g}")
    return number


def _require_integer(value: object, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return value


def validate_runtime_state(payload: Mapping[str, Any]) -> None:
    validate_release_version(payload.get("version"))
    validate_timestamp(payload.get("started_at"), "started_at")
    db_type = require_nonempty_string(payload.get("db_type"), "db_type")
    if db_type not in {"postgresql", "mariadb"}:
        raise ValueError("db_type must be postgresql or mariadb")


def validate_static_db_metrics(payload: Mapping[str, Any]) -> dict[str, str]:
    validated = {
        "db_name": require_nonempty_string(payload.get("db_name"), "db_name"),
        "db_user": require_nonempty_string(payload.get("db_user"), "db_user"),
        "db_version": require_nonempty_string(
            payload.get("db_version"),
            "db_version",
        ),
    }
    return validated


def validate_machine_event(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != EVENT_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version must be {EVENT_SCHEMA_VERSION}"
        )

    event_type = require_nonempty_string(
        payload.get("event_type"),
        "event_type",
    )
    required = EVENT_REQUIRED_FIELDS.get(event_type)
    if required is None:
        raise ValueError(f"Unsupported event_type: {event_type}")

    validate_timestamp(payload.get("observed_at"), "observed_at")

    for field in required:
        if field not in payload:
            raise ValueError(
                f"{event_type}: missing required field {field}"
            )

    if event_type.startswith("db_connection_"):
        engine = require_nonempty_string(
            payload["database_engine"],
            "database_engine",
        )
        if engine not in {"postgresql", "mariadb"}:
            raise ValueError("database_engine must be postgresql or mariadb")
        require_nonempty_string(payload["database_name"], "database_name")
        if event_type == "db_connection_restored":
            _require_integer(
                payload["outage_seconds"],
                "outage_seconds",
                minimum=0,
            )
        if "error" in payload and payload["error"] is not None:
            require_nonempty_string(payload["error"], "error")

    if event_type.startswith("recorder_writing_"):
        _require_integer(
            payload["stale_threshold_seconds"],
            "stale_threshold_seconds",
            minimum=1,
        )
        if payload.get("last_record_at") is not None:
            validate_timestamp(
                payload["last_record_at"],
                "last_record_at",
            )
        if payload.get("last_age_seconds") is not None:
            _require_integer(
                payload["last_age_seconds"],
                "last_age_seconds",
                minimum=0,
            )

    if event_type.startswith("storage_usage_"):
        for field in (
            "used_percent",
            "used_gb",
            "free_gb",
            "total_gb",
            "threshold_percent",
        ):
            _require_number(payload[field], field, minimum=0)
        require_nonempty_string(payload["cause"], "cause")

    for presentation_field in ("title", "message"):
        if presentation_field in payload:
            raise ValueError(
                f"Machine event must not contain presentation field "
                f"{presentation_field}"
            )
