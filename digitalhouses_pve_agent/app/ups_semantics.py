from __future__ import annotations


_STATUS_MAP = {
    "OL": "online",
    "OB": "on_battery",
    "LB": "low_battery",
    "HB": "high_battery",
    "RB": "replace_battery",
    "BYPASS": "bypass",
    "CAL": "calibration",
    "OFF": "output_off",
    "OVER": "overload",
    "TRIM": "trim",
    "BOOST": "boost",
    "FSD": "forced_shutdown",
    "ALARM": "alarm",
}

CANONICAL_STATUS_ORDER: tuple[str, ...] = tuple(_STATUS_MAP.values())

PRIMARY_STATUS_PRECEDENCE: tuple[str, ...] = (
    "forced_shutdown",
    "alarm",
    "overload",
    "replace_battery",
    "low_battery",
    "bypass",
    "calibration",
    "output_off",
    "on_battery",
    "boost",
    "trim",
    "high_battery",
    "online",
)

_DIRECT_CHARGER_STATUSES = frozenset(
    {"charging", "discharging", "floating", "resting"}
)


def normalize_ups_status(status_tokens: tuple[str, ...]) -> tuple[str, ...]:
    """Return the recognized UPS status set in stable canonical order."""
    recognized = {
        mapped
        for token in status_tokens
        if (mapped := _STATUS_MAP.get(str(token).strip().upper())) is not None
    }
    return tuple(status for status in CANONICAL_STATUS_ORDER if status in recognized)


def primary_ups_status(status_set: tuple[str, ...]) -> str:
    """Resolve one deterministic state while preserving the full set elsewhere."""
    known = set(status_set)
    for status in PRIMARY_STATUS_PRECEDENCE:
        if status in known:
            return status
    return "unknown"


def resolve_charger_status(
    *,
    direct_status: str | None,
    status_tokens: tuple[str, ...],
    line_power: bool,
) -> str:
    """Resolve canonical charger state from authoritative then fallback evidence."""
    if direct_status is not None:
        normalized_direct = str(direct_status).strip().casefold()
        if normalized_direct in _DIRECT_CHARGER_STATUSES:
            return normalized_direct
        return "unknown"

    token_set = {str(token).strip().upper() for token in status_tokens}
    charging = "CHRG" in token_set
    discharging = "DISCHRG" in token_set
    if charging and not discharging:
        return "charging"
    if discharging and not charging:
        return "discharging"
    if charging and discharging:
        return "unknown"
    if line_power:
        return "idle"
    return "unknown"
