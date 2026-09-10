from __future__ import annotations

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
        },
    }

    for key, spec in SETTING_SPECS.items():
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
