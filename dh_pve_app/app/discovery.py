from __future__ import annotations

import json
from typing import Any

from .config import AppConfig
from .identity import HostIdentity
from .runtime_settings import SETTING_SPECS
from .topics import build_topics


def _availability(topic: str) -> dict[str, str]:
    return {
        "topic": topic,
        "payload_available": "online",
        "payload_not_available": "offline",
    }


def _subsystem_availability(
    state_topic: str,
    subsystem: str,
) -> dict[str, str]:
    return {
        "topic": state_topic,
        "value_template": (
            "{{ 'online' if value_json.subsystems."
            + subsystem
            + ".available | default(false) else 'offline' }}"
        ),
        "payload_available": "online",
        "payload_not_available": "offline",
    }


def _semantic_attrs(
    *,
    section: str,
    subject: str,
    metric: str,
    object_id: str,
    display_name: str,
    sort_key: str,
    extra_fields: tuple[str, ...] = (),
) -> str:
    fields = [
        "'proxmox_integration':'dh_pve_app'",
        f"'proxmox_section':{json.dumps(section)}",
        f"'proxmox_subject':{json.dumps(subject)}",
        f"'proxmox_metric':{json.dumps(metric)}",
        f"'proxmox_object_id':{json.dumps(object_id)}",
        f"'proxmox_display_name':{json.dumps(display_name)}",
        f"'proxmox_sort_key':{json.dumps(sort_key)}",
        *extra_fields,
    ]
    return "{{ {" + ",".join(fields) + "} | tojson }}"


def build_discovery_payload(
    config: AppConfig,
    identity: HostIdentity,
    *,
    version: str,
) -> dict[str, Any]:
    topics = build_topics(config.mqtt, identity)

    def uid(component: str) -> str:
        return f"{topics.device_id}_{component}"

    components: dict[str, Any] = {
        "last_refresh": {
            "platform": "sensor",
            "name": "Last refresh",
            "unique_id": uid("last_refresh"),
            "default_entity_id": "sensor.dh_pve_last_refresh",
            "state_topic": topics.state,
            "value_template": "{{ value_json.last_refresh }}",
            "availability": [_availability(topics.availability)],
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "device_class": "timestamp",
            "icon": "mdi:refresh",
            "json_attributes_topic": topics.state,
            "json_attributes_template": _semantic_attrs(
                section="control",
                subject="refresh",
                metric="last_refresh",
                object_id="refresh",
                display_name="Refresh",
                sort_key="010",
            ),
        },
        "refresh": {
            "platform": "button",
            "name": "Refresh",
            "unique_id": uid("refresh"),
            "default_entity_id": "button.dh_pve_refresh",
            "command_topic": topics.refresh,
            "payload_press": "PRESS",
            "availability": [_availability(topics.availability)],
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:refresh",
            "json_attributes_topic": topics.state,
            "json_attributes_template": _semantic_attrs(
                section="control",
                subject="refresh",
                metric="manual_refresh",
                object_id="refresh",
                display_name="Refresh",
                sort_key="011",
            ),
        },
        "fans_status": {
            "platform": "sensor",
            "name": "Fans",
            "unique_id": uid("fans_status"),
            "default_entity_id": "sensor.dh_pve_fans",
            "state_topic": topics.state,
            "value_template": (
                "{{ value_json.subsystems.fans.data.status | default('unknown') }}"
            ),
            "availability": [
                _availability(topics.availability),
                _subsystem_availability(topics.state, "fans"),
            ],
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:fan-off",
            "json_attributes_topic": topics.state,
            "json_attributes_template": _semantic_attrs(
                section="cooling",
                subject="fan",
                metric="detection",
                object_id="fans",
                display_name="Fans",
                sort_key="600_000",
                extra_fields=(
                    "'count':value_json.subsystems.fans.data.count | default(0)",
                    "'detected':value_json.subsystems.fans.data.detected | default(false)",
                ),
            ),
        },
    }

    for index, (key, spec) in enumerate(SETTING_SPECS.items(), start=1):
        component_key = f"setting_{key}"
        component: dict[str, Any] = {
            "platform": "number",
            "name": spec.name,
            "unique_id": uid(component_key),
            "default_entity_id": spec.entity_id,
            "command_topic": f"{topics.settings_prefix}/{key}/set",
            "state_topic": f"{topics.settings_prefix}/{key}/state",
            "min": spec.minimum,
            "max": spec.maximum,
            "step": spec.step,
            "mode": "box",
            "entity_category": "config",
            "availability": [_availability(topics.availability)],
            "availability_mode": "all",
            "json_attributes_topic": topics.state,
            "json_attributes_template": _semantic_attrs(
                section="settings",
                subject="setting",
                metric=key,
                object_id=key,
                display_name=spec.name,
                sort_key=f"800_{index:03d}",
            ),
        }
        if spec.unit:
            component["unit_of_measurement"] = spec.unit
        components[component_key] = component

    return {
        "device": {
            "identifiers": [topics.device_id],
            "name": "DH PVE",
            "manufacturer": "DigitalHouses",
            "model": "Proxmox VE Monitoring",
            "sw_version": version,
        },
        "origin": {
            "name": "DigitalHouses DH PVE App",
            "sw_version": version,
            "support_url": (
                "https://github.com/DigitalHouses/home-assistant-apps/"
                "tree/main/dh_pve_app"
            ),
        },
        "components": components,
    }
