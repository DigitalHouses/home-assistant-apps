from __future__ import annotations

from dataclasses import dataclass


_STATUS_USER_EVENTS: dict[str, tuple[str, str]] = {
    "on_battery": ("line_power_lost", "line_power_restored"),
    "low_battery": ("low_battery_started", "low_battery_cleared"),
    "high_battery": ("high_battery_started", "high_battery_cleared"),
    "replace_battery": ("replace_battery_started", "replace_battery_cleared"),
    "bypass": ("bypass_started", "bypass_ended"),
    "calibration": ("calibration_started", "calibration_ended"),
    "output_off": ("output_off", "output_restored"),
    "overload": ("overload_started", "overload_cleared"),
    "trim": ("trim_started", "trim_ended"),
    "boost": ("boost_started", "boost_ended"),
    "forced_shutdown": ("forced_shutdown_started", "forced_shutdown_cleared"),
    "alarm": ("alarm_started", "alarm_cleared"),
}


def semantic_status_events(
    *,
    previous_status: tuple[str, ...],
    current_status: tuple[str, ...],
    previous_raw_status: tuple[str, ...],
    current_raw_status: tuple[str, ...],
    observed_at: str,
    battery_charge_percent: float | None,
    battery_runtime_seconds: float | None,
    context: dict[str, object] | None = None,
) -> tuple[tuple[str, dict[str, object]], ...]:
    """Expand one canonical UPS status transition into user-semantic Events."""

    previous = set(previous_status)
    current = set(current_status)
    events: list[tuple[str, dict[str, object]]] = []

    def add(event_type: str) -> None:
        payload: dict[str, object] = {
            "schema_version": 2,
            "event_type": event_type,
            "observed_at": observed_at,
            "previous_status": list(previous_status),
            "current_status": list(current_status),
            "previous_raw_status": list(previous_raw_status),
            "current_raw_status": list(current_raw_status),
            "battery_charge_percent": battery_charge_percent,
            "battery_runtime_seconds": battery_runtime_seconds,
        }
        if context:
            payload.update(
                {
                    str(key): value
                    for key, value in context.items()
                    if value is not None
                }
            )
        events.append((f"{event_type}:{observed_at}", payload))

    for status, (entered_event, cleared_event) in _STATUS_USER_EVENTS.items():
        if status in current and status not in previous:
            add(entered_event)
        elif status in previous and status not in current:
            add(cleared_event)

    return tuple(events)


@dataclass
class UpsStatusEventTracker:
    previous_status: tuple[str, ...] | None = None
    previous_raw_status: tuple[str, ...] | None = None

    def observe(
        self,
        *,
        current_status: tuple[str, ...],
        current_raw_status: tuple[str, ...],
        observed_at: str,
    ) -> tuple[str, dict[str, object]] | None:
        current_status = tuple(current_status)
        current_raw_status = tuple(current_raw_status)

        if self.previous_status is None:
            self.previous_status = current_status
            self.previous_raw_status = current_raw_status
            return None

        previous_status = self.previous_status
        previous_raw_status = self.previous_raw_status or ()

        self.previous_status = current_status
        self.previous_raw_status = current_raw_status

        if previous_status == current_status:
            return None

        payload: dict[str, object] = {
            "schema_version": 2,
            "event_type": "ups_status_changed",
            "observed_at": observed_at,
            "previous_status": list(previous_status),
            "current_status": list(current_status),
            "previous_raw_status": list(previous_raw_status),
            "current_raw_status": list(current_raw_status),
        }
        key = (
            f"ups_status_changed:{observed_at}:"
            f"{','.join(previous_status)}->{','.join(current_status)}"
        )
        return key, payload
