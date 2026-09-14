from __future__ import annotations

import re
from collections.abc import Mapping

from .topics import state_group_topic

_ENTITY_SEGMENT = re.compile(r"[^a-z0-9]+")
_STATE_SEGMENT = re.compile(r"[^a-z0-9_.-]+")


def _entity_slug(value: object) -> str:
    text = _ENTITY_SEGMENT.sub("_", str(value).lower()).strip("_")
    return re.sub(r"_+", "_", text) or "unknown"


def _state_slug(value: object) -> str:
    text = _STATE_SEGMENT.sub("_", str(value).casefold()).strip("_.-")
    return text or "unknown"


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _drop_json_attribute(component: object, key: str) -> None:
    if not isinstance(component, dict):
        return
    template = component.get("json_attributes_template")
    if not isinstance(template, str):
        return
    component["json_attributes_template"] = re.sub(
        rf',"{re.escape(key)}":[^,}}]+',
        "",
        template,
    )


def _component_groups(inventory: Mapping[str, object]) -> dict[str, str]:
    groups = {
        "system": "host",
        "last_boot": "host",
        "previous_shutdown": "shutdown",
        "shutdown_history": "shutdown",
        "cpu_usage": "cpu",
        "cpu_temperature": "cpu",
        "cpu_frequency": "cpu",
        "cpu_throttling": "cpu",
        "memory_usage": "memory",
        "swap_usage": "memory",
        "fans_status": "fans",
        "last_refresh": "diagnostics",
        "refresh": "diagnostics",
        "vms_summary": "guest/summary",
        "lxcs_summary": "guest/summary",
    }

    for subsystem in ("host", "cpu", "memory", "storage", "smart", "gpu", "fans"):
        groups[f"collector_{subsystem}"] = f"collector/{subsystem}"

    for key in tuple(inventory):
        if str(key).startswith("setting_"):
            groups[str(key)] = "diagnostics"

    for storage_id in _mapping(inventory.get("storage")):
        entity = _entity_slug(storage_id)
        groups[f"storage_{entity}_usage"] = f"storage/{_state_slug(storage_id)}"

    for disk_id in _mapping(inventory.get("smart")):
        entity = _entity_slug(disk_id)
        runtime = _state_slug(disk_id)
        prefix = f"disk_{entity}_"
        for key in (
            "health",
            "smart_problem",
            "wear",
            "power_on_hours",
            "media_errors",
            "reallocated",
            "pending",
            "uncorrectable",
            "unsafe_shutdowns",
            "data_written",
            "daily_max_temperature",
        ):
            groups[prefix + key] = f"disk/{runtime}/status"
        groups[prefix + "temperature"] = f"disk/{runtime}/telemetry"

    for gpu_id in _mapping(inventory.get("gpu")):
        entity = _entity_slug(gpu_id)
        runtime = _state_slug(gpu_id)
        groups[f"gpu_{entity}_owner"] = f"gpu/{runtime}/status"
        groups[f"gpu_{entity}_temperature"] = f"gpu/{runtime}/telemetry"
        groups[f"gpu_{entity}_transcoding"] = f"gpu/{runtime}/telemetry"

    for fan_id in _mapping(inventory.get("fans")):
        entity = _entity_slug(fan_id)
        groups[f"fan_{entity}_rpm"] = f"fan/{_state_slug(fan_id)}"

    guests = _mapping(inventory.get("guests"))
    for plural, singular in (("vms", "vm"), ("lxcs", "lxc")):
        for guest_id in _mapping(guests.get(plural)):
            entity = _entity_slug(guest_id)
            groups[f"{singular}_{entity}_status"] = f"guest/{singular}/{_state_slug(guest_id)}"
            groups[f"{singular}_{entity}_shutdown"] = "shutdown"

    topology = _mapping(inventory.get("topology"))
    for assignment_id in _mapping(topology.get("assignments")):
        groups[f"passthrough_{_entity_slug(assignment_id)}"] = "topology"

    return groups


def _route_disk_temperature_object_availability(
    components: Mapping[str, object],
    topics,
    inventory: Mapping[str, object],
) -> None:
    """Keep per-disk availability on the discrete status topic.

    Disk temperature state is published on an adaptive telemetry topic, while
    the disk object's available flag belongs to the change-only status group.
    Home Assistant can consume those from separate MQTT topics.
    """
    for disk_id in _mapping(inventory.get("smart")):
        entity = _entity_slug(disk_id)
        runtime = _state_slug(disk_id)
        component = components.get(f"disk_{entity}_temperature")
        if not isinstance(component, dict):
            continue
        availability = component.get("availability")
        if not isinstance(availability, list):
            continue
        status_topic = state_group_topic(topics, f"disk/{runtime}/status")
        for entry in availability:
            if not isinstance(entry, dict):
                continue
            template = entry.get("value_template")
            if (
                isinstance(template, str)
                and "subsystems.smart.data" in template
                and ".available" in template
            ):
                entry["topic"] = status_topic


def _diagnostic_components(topics) -> dict[str, dict[str, object]]:
    diagnostics = state_group_topic(topics, "diagnostics")
    availability = [
        {
            "topic": topics.availability,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
    ]
    uid = lambda suffix: f"{topics.device_id}_{suffix}"
    return {
        "app_profile": {
            "platform": "sensor",
            "name": "App profile",
            "unique_id": uid("app_profile"),
            "default_entity_id": "sensor.dh_pve_app_profile",
            "state_topic": diagnostics,
            "value_template": "{{ value_json.app_profile.state | default('normal') }}",
            "availability": availability,
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:speedometer-medium",
            "json_attributes_topic": diagnostics,
            "json_attributes_template": (
                "{{ {'resources': value_json.app_profile.resources | default({}), "
                "'reason': value_json.app_profile.reason | default(none)} | tojson }}"
            ),
        },
        "last_publication": {
            "platform": "sensor",
            "name": "Last publication",
            "unique_id": uid("last_publication"),
            "default_entity_id": "sensor.dh_pve_last_publication",
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


def route_pve_discovery_groups(
    payload: dict[str, object],
    topics,
    *,
    inventory: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Route PVE Discovery entities to the smallest retained presentation group."""
    raw_components = payload.get("components")
    if not isinstance(raw_components, dict):
        return payload
    components = raw_components
    inventory = inventory or {}
    groups = _component_groups(inventory)

    for key, component in components.items():
        if key.startswith("setting_"):
            groups[key] = "diagnostics"
        group = groups.get(key)
        if group is None or not isinstance(component, dict):
            continue
        group_topic = state_group_topic(topics, group)
        if component.get("state_topic") == topics.state:
            component["state_topic"] = group_topic
        if component.get("json_attributes_topic") == topics.state:
            component["json_attributes_topic"] = group_topic
        availability = component.get("availability")
        if isinstance(availability, list):
            for entry in availability:
                if isinstance(entry, dict) and entry.get("topic") == topics.state:
                    entry["topic"] = group_topic

    _route_disk_temperature_object_availability(components, topics, inventory)

    _drop_json_attribute(components.get("memory_usage"), "used_gib")
    for key, component in components.items():
        if key.startswith("storage_") and key.endswith("_usage"):
            _drop_json_attribute(component, "used_gib")
            _drop_json_attribute(component, "status")

    components.update(_diagnostic_components(topics))
    return payload
