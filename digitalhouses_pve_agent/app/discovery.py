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
        "'proxmox_integration':'digitalhouses_pve_agent'",
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
            "default_entity_id": "sensor.dh_pve_agent_last_refresh",
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
            "default_entity_id": "button.dh_pve_agent_refresh",
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
        "restart_agent": {
            "platform": "button",
            "name": "Restart Agent",
            "unique_id": uid("restart_agent"),
            "default_entity_id": "button.dh_pve_agent_restart_agent",
            "command_topic": topics.restart_agent,
            "payload_press": "PRESS",
            "qos": 1,
            "retain": False,
            "device_class": "restart",
            "availability": [_availability(topics.availability)],
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:restart",
            "json_attributes_topic": topics.state,
            "json_attributes_template": _semantic_attrs(
                section="control",
                subject="agent",
                metric="restart",
                object_id="restart_agent",
                display_name="Restart Agent",
                sort_key="012",
            ),
        },
        "check_updates": {
            "platform": "button",
            "name": "Check updates",
            "unique_id": uid("check_updates"),
            "default_entity_id": "button.dh_pve_agent_check_updates",
            "command_topic": topics.update_check,
            "payload_press": "PRESS",
            "qos": 1,
            "retain": False,
            "availability": [_availability(topics.availability)],
            "entity_category": "diagnostic",
            "icon": "mdi:cloud-search",
        },
        "update": {
            "platform": "button",
            "name": "Install update",
            "unique_id": uid("update"),
            "default_entity_id": "button.dh_pve_agent_update",
            "command_topic": topics.update_install,
            "payload_press": "PRESS",
            "qos": 1,
            "retain": False,
            "availability": [_availability(topics.availability)],
            "entity_category": "diagnostic",
            "icon": "mdi:package-down",
        },
        "update_available": {
            "platform": "binary_sensor",
            "name": "Update available",
            "unique_id": uid("update_available"),
            "default_entity_id": "binary_sensor.dh_pve_agent_update_available",
            "state_topic": topics.update_state,
            "value_template": (
                "{{ 'ON' if value_json.available == true "
                "else 'OFF' if value_json.available == false else 'unknown' }}"
            ),
            "payload_on": "ON",
            "payload_off": "OFF",
            "availability": [_availability(topics.availability)],
            "entity_category": "diagnostic",
            "icon": "mdi:package-up",
        },
        "latest_version": {
            "platform": "sensor",
            "name": "Latest release",
            "unique_id": uid("latest_version"),
            "default_entity_id": "sensor.dh_pve_agent_latest_version",
            "state_topic": topics.update_state,
            "value_template": "{{ value_json.latest_version | default('unknown') }}",
            "availability": [_availability(topics.availability)],
            "entity_category": "diagnostic",
            "icon": "mdi:tag-check",
        },
        "update_status": {
            "platform": "sensor",
            "name": "Update status",
            "unique_id": uid("update_status"),
            "default_entity_id": "sensor.dh_pve_agent_update_status",
            "state_topic": topics.update_state,
            "value_template": "{{ value_json.status | default('idle') }}",
            "availability": [_availability(topics.availability)],
            "entity_category": "diagnostic",
            "icon": "mdi:progress-wrench",
            "json_attributes_topic": topics.update_state,
            "json_attributes_template": (
                "{{ {'error': value_json.error | default(none), "
                "'checked_at': value_json.checked_at | default(none), "
                "'installed_version': value_json.installed_version | default(none), "
                "'installation_status': value_json.installation_status | default(none), "
                "'installation_error': value_json.installation_error | default(none)} | tojson }}"
            ),
        },
        "refresh_state": {
            "platform": "sensor",
            "name": "Refresh state",
            "unique_id": uid("refresh_state"),
            "default_entity_id": "sensor.dh_pve_agent_refresh_state",
            "state_topic": topics.refresh_operation,
            "value_template": "{{ value_json.state | default('idle') }}",
            "availability": [_availability(topics.availability)],
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:progress-clock",
            "json_attributes_topic": topics.refresh_operation,
            "json_attributes_template": (
                "{{ {'started_at': value_json.started_at | default(none), "
                "'finished_at': value_json.finished_at | default(none), "
                "'duration_seconds': value_json.duration_seconds | default(none), "
                "'error': value_json.error | default(none)} | tojson }}"
            ),
        },
        "ups_scan": {
            "platform": "button",
            "name": "Сканировать UPS",
            "unique_id": uid("ups_scan"),
            "default_entity_id": "button.dh_pve_agent_scan_ups",
            "command_topic": topics.ups_scan,
            "payload_press": "PRESS",
            "availability": [_availability(topics.availability)],
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:power-plug-battery-outline",
        },
        "ups_scan_state": {
            "platform": "sensor",
            "name": "UPS scan state",
            "unique_id": uid("ups_scan_state"),
            "default_entity_id": "sensor.dh_pve_agent_ups_scan_state",
            "state_topic": topics.ups_scan_operation,
            "value_template": "{{ value_json.state | default('idle') }}",
            "availability": [_availability(topics.availability)],
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:magnify-scan",
            "json_attributes_topic": topics.ups_scan_operation,
            "json_attributes_template": (
                "{{ {'started_at': value_json.started_at | default(none), "
                "'finished_at': value_json.finished_at | default(none), "
                "'duration_seconds': value_json.duration_seconds | default(none), "
                "'error': value_json.error | default(none)} | tojson }}"
            ),
        },
        "ups_scan_result": {
            "platform": "sensor",
            "name": "UPS scan result",
            "unique_id": uid("ups_scan_result"),
            "default_entity_id": "sensor.dh_pve_agent_ups_scan_result",
            "state_topic": topics.ups_scan_state,
            "value_template": "{{ value_json.result | default('Не выполнялось') }}",
            "availability": [_availability(topics.availability)],
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:magnify-scan",
            "json_attributes_topic": topics.ups_scan_state,
            "json_attributes_template": (
                "{{ {'count': value_json.count | default(0), "
                "'names': value_json.names | default([])} | tojson }}"
            ),
        },
        "ups_last_scan": {
            "platform": "sensor",
            "name": "UPS last scan",
            "unique_id": uid("ups_last_scan"),
            "default_entity_id": "sensor.dh_pve_agent_ups_last_scan",
            "state_topic": topics.ups_scan_state,
            "value_template": "{{ value_json.last_scan | default(none) }}",
            "availability": [_availability(topics.availability)],
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "device_class": "timestamp",
            "icon": "mdi:clock-check-outline",
        },
        "fans_status": {
            "platform": "sensor",
            "name": "Fans",
            "unique_id": uid("fans_status"),
            "default_entity_id": "sensor.dh_pve_agent_fans",
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
                    "'candidate_count':value_json.subsystems.fans.data.candidate_count | default(0)",
                    "'confirmed_count':value_json.subsystems.fans.data.confirmed_count | default(0)",
                    "'unconfirmed_count':value_json.subsystems.fans.data.unconfirmed_count | default(0)",
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
            "name": "DigitalHouses PVE Agent",
            "sw_version": version,
            "support_url": (
                "https://github.com/DigitalHouses/home-assistant-apps/"
                "tree/main/digitalhouses_pve_agent"
            ),
        },
        "components": components,
    }
