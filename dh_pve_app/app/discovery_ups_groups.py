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
    "battery_charger_status",
}

_CONFIG = {
    "capabilities",
    "shutdown_policy",
    "policy_power_restore_delay_observed",
    "policy_charge_threshold",
    "policy_runtime_reserve",
    "policy_apply",
    "nominal_real_power",
    "battery_charge_warning",
    "battery_charge_low",
    "battery_runtime_low",
    "ups_shutdown_delay",
    "ups_start_delay",
}

_TESTS = {
    "test_result",
    "beeper_status",
    "beeper",
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
    "guest_shutdown_budget",
    "shutdown_budget",
    "shutdown_readiness",
    "ups_app_profile",
    "ups_last_publication",
}

_PROBLEM_NAMES = {
    "nut_unavailable": "NUT unavailable",
    "on_battery": "On battery",
    "low_battery": "Low battery",
    "overload": "Overload",
    "replace_battery": "Replace battery",
    "bypass": "Bypass",
    "power_state_unknown": "Power state unknown",
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


def _availability(topics) -> list[dict[str, str]]:
    return [
        {
            "topic": topics.availability,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
    ]


def _adaptive_diagnostic_components(topics) -> dict[str, dict[str, object]]:
    diagnostics = ups_state_group_topic(topics, "diagnostics")
    availability = _availability(topics)
    uid = lambda suffix: f"{topics.device_id}_{suffix}"
    return {
        "ups_app_profile": {
            "platform": "sensor",
            "name": "App profile",
            "unique_id": uid("app_profile"),
            "default_entity_id": "sensor.dh_pve_ups_app_profile",
            "state_topic": diagnostics,
            "value_template": "{{ value_json.app_profile.state | default('normal') }}",
            "availability": availability,
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:speedometer-medium",
            "json_attributes_topic": diagnostics,
            "json_attributes_template": (
                "{{ {'reason': value_json.app_profile.reason | default(none)} | tojson }}"
            ),
        },
        "ups_last_publication": {
            "platform": "sensor",
            "name": "Last publication",
            "unique_id": uid("last_publication"),
            "default_entity_id": "sensor.dh_pve_ups_last_publication",
            "state_topic": diagnostics,
            "value_template": "{{ value_json.last_publication.timestamp | default(none) }}",
            "availability": availability,
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "device_class": "timestamp",
            "icon": "mdi:publish",
            "json_attributes_topic": diagnostics,
            "json_attributes_template": (
                "{{ {'group': value_json.last_publication.group | default(none), "
                "'reason': value_json.last_publication.reason | default(none), "
                "'profile': value_json.last_publication.profile | default(none), "
                "'group_count': value_json.last_publication.group_count | default(0)} | tojson }}"
            ),
        },
    }


def _line_power_components(topics) -> dict[str, dict[str, object]]:
    state_topic = ups_state_group_topic(topics, "line_power_statistics")
    availability = _availability(topics)
    uid = lambda suffix: f"{topics.device_id}_{suffix}"

    line_state_availability = availability + [
        {
            "topic": state_topic,
            "value_template": (
                "{{ 'online' if value_json.state | default('unknown') "
                "in ['online', 'offline'] else 'offline' }}"
            ),
            "payload_available": "online",
            "payload_not_available": "offline",
        }
    ]

    components: dict[str, dict[str, object]] = {
        "line_power": {
            "platform": "binary_sensor",
            "name": "Line power",
            "unique_id": uid("line_power"),
            "default_entity_id": "binary_sensor.dh_app_pve_ups_line_power",
            "state_topic": state_topic,
            "value_template": (
                "{{ 'ON' if value_json.state | default('unknown') == 'online' else 'OFF' }}"
            ),
            "payload_on": "ON",
            "payload_off": "OFF",
            "availability": line_state_availability,
            "availability_mode": "all",
            "device_class": "power",
            "icon": "mdi:transmission-tower",
        },
        "line_power_online_month": {
            "platform": "sensor",
            "name": "Line power online this month",
            "unique_id": uid("line_power_online_month"),
            "default_entity_id": "sensor.dh_app_pve_ups_line_power_online_month",
            "state_topic": state_topic,
            "value_template": "{{ value_json.online_seconds | default(none) }}",
            "unit_of_measurement": "s",
            "device_class": "duration",
            "availability": availability,
            "availability_mode": "all",
            "icon": "mdi:transmission-tower-export",
        },
        "line_power_offline_month": {
            "platform": "sensor",
            "name": "Line power offline this month",
            "unique_id": uid("line_power_offline_month"),
            "default_entity_id": "sensor.dh_app_pve_ups_line_power_offline_month",
            "state_topic": state_topic,
            "value_template": "{{ value_json.offline_seconds | default(none) }}",
            "unit_of_measurement": "s",
            "device_class": "duration",
            "availability": availability,
            "availability_mode": "all",
            "icon": "mdi:transmission-tower-off",
        },
        "line_power_outages_month": {
            "platform": "sensor",
            "name": "Line power outages this month",
            "unique_id": uid("line_power_outages_month"),
            "default_entity_id": "sensor.dh_app_pve_ups_line_power_outages_month",
            "state_topic": state_topic,
            "value_template": "{{ value_json.outages_month | default(none) }}",
            "availability": availability,
            "availability_mode": "all",
            "icon": "mdi:counter",
        },
        "line_power_availability_month": {
            "platform": "sensor",
            "name": "Line power availability this month",
            "unique_id": uid("line_power_availability_month"),
            "default_entity_id": "sensor.dh_app_pve_ups_line_power_availability_month",
            "state_topic": state_topic,
            "value_template": "{{ value_json.availability_percent | default(none) }}",
            "unit_of_measurement": "%",
            "availability": availability,
            "availability_mode": "all",
            "icon": "mdi:percent-outline",
            "json_attributes_topic": state_topic,
            "json_attributes_template": (
                "{{ {'month_key': value_json.month_key | default(none), "
                "'month_label_ru': value_json.month_label_ru | default(none), "
                "'tracking_since': value_json.tracking_since | default(none), "
                "'partial_month': value_json.partial_month | default(true)} | tojson }}"
            ),
        },
        "line_power_current_outage_started": {
            "platform": "sensor",
            "name": "Current line power outage started",
            "unique_id": uid("line_power_current_outage_started"),
            "default_entity_id": (
                "sensor.dh_app_pve_ups_line_power_current_outage_started"
            ),
            "state_topic": state_topic,
            "value_template": "{{ value_json.current_outage_started | default(none) }}",
            "device_class": "timestamp",
            "availability": availability,
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:power-plug-off-outline",
        },
        "line_power_last_failure": {
            "platform": "sensor",
            "name": "Last line power failure",
            "unique_id": uid("line_power_last_failure"),
            "default_entity_id": "sensor.dh_app_pve_ups_line_power_last_failure",
            "state_topic": state_topic,
            "value_template": "{{ value_json.last_failure | default(none) }}",
            "device_class": "timestamp",
            "availability": availability,
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:transmission-tower-off",
        },
        "line_power_last_restore": {
            "platform": "sensor",
            "name": "Last line power restore",
            "unique_id": uid("line_power_last_restore"),
            "default_entity_id": "sensor.dh_app_pve_ups_line_power_last_restore",
            "state_topic": state_topic,
            "value_template": "{{ value_json.last_restore | default(none) }}",
            "device_class": "timestamp",
            "availability": availability,
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:transmission-tower-import",
        },
        "line_power_last_outage_duration": {
            "platform": "sensor",
            "name": "Last line power outage duration",
            "unique_id": uid("line_power_last_outage_duration"),
            "default_entity_id": (
                "sensor.dh_app_pve_ups_line_power_last_outage_duration"
            ),
            "state_topic": state_topic,
            "value_template": (
                "{{ value_json.last_outage_duration_seconds | default(none) }}"
            ),
            "unit_of_measurement": "s",
            "device_class": "duration",
            "availability": availability,
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:timer-outline",
        },
    }
    return components


def _canonicalize_entity_id(value: object) -> object:
    if not isinstance(value, str):
        return value
    if ".dh_pve_ups_" in value:
        return value.replace(".dh_pve_ups_", ".dh_app_pve_ups_", 1)
    if ".dh_ups_" in value:
        return value.replace(".dh_ups_", ".dh_app_pve_ups_", 1)
    return value


def _problem_components(topics) -> dict[str, dict[str, object]]:
    availability = _availability(topics)
    uid = lambda suffix: f"{topics.device_id}_{suffix}"
    components: dict[str, dict[str, object]] = {}

    for problem_id, name in _PROBLEM_NAMES.items():
        components[f"{problem_id}_problem"] = {
            "platform": "binary_sensor",
            "name": name,
            "unique_id": uid(f"{problem_id}_problem"),
            "default_entity_id": f"binary_sensor.dh_app_pve_ups_{problem_id}_problem",
            "state_topic": f"{topics.base}/problems/{problem_id}/state",
            "payload_on": "ON",
            "payload_off": "OFF",
            "availability": availability,
            "availability_mode": "all",
            "device_class": "problem",
            "entity_category": "diagnostic",
        }

    components["problems"] = {
        "platform": "sensor",
        "name": "Problems",
        "unique_id": uid("problems"),
        "default_entity_id": "sensor.dh_app_pve_ups_problems",
        "state_topic": f"{topics.base}/problems/aggregate",
        "availability": availability,
        "availability_mode": "all",
        "entity_category": "diagnostic",
        "icon": "mdi:alert-circle-outline",
        "json_attributes_topic": f"{topics.base}/problems/presentation",
    }
    components["diagnostic_event"] = {
        "platform": "event",
        "name": "Diagnostic",
        "unique_id": uid("diagnostic_event"),
        "default_entity_id": "event.dh_app_pve_ups_diagnostic",
        "state_topic": topics.diagnostic_event,
        "event_types": [
            "problem_started",
            "problem_recovered",
            "problem_updated",
            "config_changed",
        ],
        "qos": 1,
        "availability": availability,
        "availability_mode": "all",
        "entity_category": "diagnostic",
        "icon": "mdi:alert-circle-outline",
    }
    return components


def route_ups_discovery_groups(payload: dict[str, object], topics) -> dict[str, object]:
    """Route UPS Discovery to canonical retained presentation groups."""
    raw_components = payload.get("components")
    if not isinstance(raw_components, dict):
        return payload

    raw_components.pop("battery_runtime", None)
    raw_components.pop("policy_on_battery_delay_observed", None)
    raw_components.update(_adaptive_diagnostic_components(topics))

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

        if "default_entity_id" in component:
            component["default_entity_id"] = _canonicalize_entity_id(
                component.get("default_entity_id")
            )

    # App-owned problem state is a separate retained contract and intentionally
    # replaces the aggregate that used to be derived from the monolithic UPS
    # status JSON. Raw UPS status binaries remain available as telemetry.
    raw_components.update(_problem_components(topics))
    raw_components.update(_line_power_components(topics))
    return payload
