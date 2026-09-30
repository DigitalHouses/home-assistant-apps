"""Machine-event contract validation for DigitalHouses Internet App."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping

EVENT_SCHEMA_VERSION = 2

_REASON_VALUES = {"low_download", "low_upload", "high_ping"}
_TARGET_VALUES = {"ont", "router"}
_ACTION_VALUES = {"button", "switch"}
_MODE_VALUES = {"smart", "both"}
_SPEEDTEST_SOURCE_VALUES = {"manual", "automatic"}


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_int(value: Any, *, minimum: int = 0) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= minimum
    )


def _is_number(value: Any, *, minimum: float = 0.0) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value) >= minimum
    )


def _is_optional_number(value: Any) -> bool:
    return value is None or _is_number(value)


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_enum(values: set[str]) -> Callable[[Any], bool]:
    return lambda value: isinstance(value, str) and value in values


def _is_string_list(
    value: Any,
    *,
    allowed: set[str] | None = None,
    allow_empty: bool = False,
) -> bool:
    if not isinstance(value, list):
        return False
    if not allow_empty and not value:
        return False
    if any(not isinstance(item, str) or not item for item in value):
        return False
    if allowed is not None and any(item not in allowed for item in value):
        return False
    return True


Validator = Callable[[Any], bool]

_EVENT_FIELDS: dict[str, dict[str, Validator]] = {
    "connection_lost": {
        "router_up": _is_bool,
        "attempts": lambda value: _is_int(value, minimum=1),
    },
    "connection_restored": {
        "duration_seconds": lambda value: _is_int(value, minimum=0),
    },
    "recovery_started": {
        "cycle": lambda value: _is_int(value, minimum=1),
        "mode": _is_enum(_MODE_VALUES),
        "targets": lambda value: _is_string_list(
            value,
            allowed=_TARGET_VALUES,
        ),
        "reason": _is_nonempty_string,
    },
    "recovery_action": {
        "cycle": lambda value: _is_int(value, minimum=1),
        "target": _is_enum(_TARGET_VALUES),
        "action": _is_enum(_ACTION_VALUES),
        "entity_id": _is_nonempty_string,
    },
    "recovery_stopped": {
        "reason": _is_nonempty_string,
    },
    "recovery_exhausted": {
        "cycles": lambda value: _is_int(value, minimum=1),
        "cooldown_seconds": lambda value: _is_int(value, minimum=0),
    },
    "recovery_error": {
        "error": _is_nonempty_string,
    },
    "speedtest_completed": {
        "download_mbps": _is_number,
        "upload_mbps": _is_number,
        "ping_ms": _is_number,
        "jitter_ms": _is_optional_number,
        "packet_loss_pct": _is_optional_number,
    },
    "speedtest_failed": {
        "reason": _is_nonempty_string,
        "source": _is_enum(_SPEEDTEST_SOURCE_VALUES),
        "automatic_failure_streak": lambda value: _is_int(value, minimum=0),
    },
    "performance_problem_started": {
        "reasons": lambda value: _is_string_list(
            value,
            allowed=_REASON_VALUES,
        ),
        "download_mbps": _is_number,
        "upload_mbps": _is_number,
        "ping_ms": _is_number,
        "minimum_download_mbps": _is_number,
        "minimum_upload_mbps": _is_number,
        "maximum_ping_ms": _is_number,
    },
    "performance_problem_recovered": {
        "previous_reasons": lambda value: _is_string_list(
            value,
            allowed=_REASON_VALUES,
        ),
        "download_mbps": _is_number,
        "upload_mbps": _is_number,
        "ping_ms": _is_number,
    },
    "performance_problem_updated": {
        "previous_reasons": lambda value: _is_string_list(
            value,
            allowed=_REASON_VALUES,
        ),
        "reasons": lambda value: _is_string_list(
            value,
            allowed=_REASON_VALUES,
        ),
        "download_mbps": _is_number,
        "upload_mbps": _is_number,
        "ping_ms": _is_number,
    },
}


def _validate_timestamp(value: Any) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be a non-empty ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("timestamp must be valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")


def validate_machine_event(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != EVENT_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version must be {EVENT_SCHEMA_VERSION}"
        )

    event_type = payload.get("event_type")
    if not isinstance(event_type, str) or event_type not in _EVENT_FIELDS:
        raise ValueError(f"unsupported event_type: {event_type!r}")

    _validate_timestamp(payload.get("timestamp"))

    fields = _EVENT_FIELDS[event_type]
    expected = {"schema_version", "event_type", "timestamp", *fields}
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"{event_type} fields mismatch: missing={missing}, extra={extra}"
        )

    for field, validator in fields.items():
        value = payload[field]
        if not validator(value):
            raise ValueError(
                f"{event_type}.{field} has invalid value {value!r}"
            )
