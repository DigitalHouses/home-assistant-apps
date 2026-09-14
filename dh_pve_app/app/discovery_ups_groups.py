from __future__ import annotations

from .topics import ups_state_group_topic


_TELEMETRY = {
    "battery_charge",
    "battery_runtime_minutes",
    "battery_voltage",
    "load",
    "input_voltage",
    "output_voltage",
    "input_frequency",
    "output_frequency",
}

_STATUS = {
    "status",
    "problems",
    "available",
    "on_battery",
    "low_battery",
    "replace_battery",
    "overload",
    "bypass",
    "charging",
    "discharging",
}

_CONFIG = {
    "capabilities",
    "shutdown_policy",
    "policy_on_battery_delay_observed",
    "policy_power_restore_delay_observed",
    "nominal_real_power",
    "battery_charge_warning",
    "battery_charge_low",
    "battery_runtime_low",
    "ups_shutdown_delay",
    "ups_start_delay",
    "guest_shutdown_budget",
}

_TESTS = {
    "test_result",
    "beeper_status",
    "test_quick_interval_days",
    "test_quick_time",
    "test_deep_interval_days",
    "test_deep_time",
    "test_state",
    "last_quick_test",
    "next_quick_test",
    "last_deep_test",
    "next_deep_test",
    "test_history",
}

_DIAGNOSTICS = {
    "last_refresh",
    "shutdown_readiness",
}


def _group_for(component_key: str) -> str | None:
    if component_key in _TELEMETRY:
        return "telemetry"
    if component_key in _STATUS:
        return "status"
    if component_key in _CONFIG:
        return "config"
    if component_key in _TESTS:
        return "tests"
    if component_key in _DIAGNOSTICS:
        return "diagnostics"
    return None


def route_ups_discovery_groups(payload: dict[str, object], topics) -> dict[str, object]:
    """Route UPS Discovery state to independent retained presentation groups.

    NUT availability always reads the status group. Telemetry groups are
    intentionally not refreshed just to announce a NUT outage. The legacy
    seconds runtime sensor is removed here so production Discovery exposes one
    canonical runtime entity in minutes while the raw seconds value may remain
    available inside the application payload for compatibility.
    """
    raw_components = payload.get("components")
    if not isinstance(raw_components, dict):
        return payload

    raw_components.pop("battery_runtime", None)

    legacy_state = topics.state
    status_topic = ups_state_group_topic(topics, "status")

    for key, component in raw_components.items():
        if not isinstance(component, dict):
            continue

        group = _group_for(str(key))
        if group is not None:
            group_topic = ups_state_group_topic(topics, group)
            if component.get("state_topic") == legacy_state:
                component["state_topic"] = group_topic
            if component.get("json_attributes_topic") == legacy_state:
                component["json_attributes_topic"] = group_topic

        availability = component.get("availability")
        if isinstance(availability, list):
            for item in availability:
                if not isinstance(item, dict):
                    continue
                if item.get("topic") != legacy_state:
                    continue
                # Every legacy UPS state-topic availability entry tests
                # value_json.available, which now belongs to the status group.
                item["topic"] = status_topic

    return payload
