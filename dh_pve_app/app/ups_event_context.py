from __future__ import annotations

from typing import Any


_UPS_SNAPSHOT_FIELDS = (
    "manufacturer",
    "model",
    "serial",
    "battery_charge_percent",
    "runtime_seconds",
    "battery_voltage_v",
    "battery_nominal_voltage_v",
    "load_percent",
    "nominal_real_power_w",
    "input_voltage_v",
    "input_nominal_voltage_v",
    "output_voltage_v",
    "input_frequency_hz",
    "output_frequency_hz",
    "input_transfer_high_v",
    "input_transfer_low_v",
    "warning_charge_percent",
    "low_charge_percent",
    "low_runtime_seconds",
    "battery_charger_status",
)


def ups_snapshot_event_context(snapshot: object | None) -> dict[str, object]:
    if snapshot is None:
        return {}

    result: dict[str, object] = {}
    for name in _UPS_SNAPSHOT_FIELDS:
        value = getattr(snapshot, name, None)
        if value is None:
            continue
        target = "battery_runtime_seconds" if name == "runtime_seconds" else name
        result[target] = value
    return result


def line_power_event_context(tracker: object | None) -> dict[str, object]:
    if tracker is None:
        return {}
    snapshot_fn = getattr(tracker, "snapshot", None)
    if not callable(snapshot_fn):
        return {}
    try:
        snapshot: Any = snapshot_fn()
    except Exception:
        return {}

    result: dict[str, object] = {
        "outages_month": getattr(snapshot, "outages_month", None),
        "outage_started_at": (
            getattr(snapshot, "current_outage_started", None)
            or getattr(snapshot, "last_failure", None)
        ),
        "outage_restored_at": getattr(snapshot, "last_restore", None),
        "outage_duration_seconds": getattr(
            snapshot,
            "last_outage_duration_seconds",
            None,
        ),
    }
    return {
        key: value
        for key, value in result.items()
        if value is not None
    }
