"""Home Assistant MQTT Device Discovery for the read-only Zigbee Monitor.

Recorder-facing scalars never expose dynamic JSON attributes. Rich UI snapshots
are separate entities and MUST be excluded from the site's Recorder policy.
"""
from __future__ import annotations

from typing import Any

PRODUCT = "digitalhouses_zigbee_monitor_app"
PREFIX = "dh_zigbee_monitor_app"
ROOT = "DigitalHouses/Global/dh_zigbee_monitor_app"
DISCOVERY = f"homeassistant/device/{PREFIX}/config"
APP_AVAILABILITY = f"{ROOT}/availability"
HA_STATUS = "homeassistant/status"

HISTORY: dict[str, tuple[str, str | None]] = {
    "networks": ("Configured Zigbee2MQTT networks", None),
    "devices": ("Known Zigbee devices", None),
    "offline": ("Offline Zigbee devices", None),
    "spammers": ("Anomalous Zigbee devices", None),
    "incidents": ("Active Zigbee incidents", None),
    "messages_rate_5m": ("MQTT device messages per minute (5m)", "messages/min"),
}

DETAILS: dict[str, str] = {
    "networks_details": "networks",
    "offline_details": "devices",
    "inventory_details": "devices",
    "top_1h_details": "items",
    "top_24h_details": "items",
    "top_7d_details": "items",
    "incidents_details": "incidents",
}


def validity_topic(key: str) -> str:
    if key not in HISTORY and key not in DETAILS:
        raise KeyError(key)
    return f"{ROOT}/valid/{key}"


def state_topic(key: str) -> str:
    return f"{ROOT}/state/{key}"


def _availability(key: str | None = None) -> list[dict[str, str]]:
    result = [{
        "topic": APP_AVAILABILITY,
        "payload_available": "online",
        "payload_not_available": "offline",
    }]
    if key is not None:
        result.append({
            "topic": validity_topic(key),
            "payload_available": "online",
            "payload_not_available": "offline",
        })
    return result


def _component(platform: str, key: str, name: str, *, valid: bool = False,
               **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "platform": platform,
        "name": name,
        "unique_id": f"{PREFIX}_{key}",
        "default_entity_id": f"{platform}.{PREFIX}_{key}",
        "state_topic": state_topic(key),
        "availability": _availability(key if valid else None),
        "availability_mode": "all",
    }
    result.update(extra)
    return result


def build_discovery(version: str) -> dict[str, Any]:
    components: dict[str, dict[str, Any]] = {}
    for key, (name, unit) in HISTORY.items():
        args: dict[str, Any] = {
            "icon": "mdi:zigbee",
            "state_class": "measurement",
        }
        if unit is not None:
            args["unit_of_measurement"] = unit
        components[key] = _component("sensor", key, name, valid=True, **args)
        # Contract: no json_attributes_topic / json_attributes_template.
    for key in DETAILS:
        topic = state_topic(key)
        components[key] = _component(
            "sensor", key, key.replace("_", " ").capitalize(),
            valid=True,
            value_template="{{ value_json.state }}",
            json_attributes_topic=topic,
            entity_category="diagnostic",
            icon="mdi:format-list-bulleted",
        )
    components["card"] = _component(
        "sensor", "card", "Zigbee Monitor status",
        value_template="{{ value_json.state }}",
        json_attributes_topic=state_topic("card"),
        entity_category="diagnostic",
        icon="mdi:zigbee",
    )
    components["version"] = _component(
        "sensor", "version", "Version", entity_category="diagnostic")
    components["started_at"] = _component(
        "sensor", "started_at", "Started at",
        device_class="timestamp", entity_category="diagnostic")
    components["last_refresh"] = _component(
        "sensor", "last_refresh", "Last refresh",
        device_class="timestamp", entity_category="diagnostic")
    components["latest_version"] = _component(
        "sensor", "latest_version", "Latest version",
        entity_category="diagnostic")
    components["update_available"] = _component(
        "binary_sensor", "update_available", "Update available",
        payload_on="ON", payload_off="OFF", entity_category="diagnostic")
    for key, name in [("refresh", "Refresh data"), ("check_updates", "Check version")]:
        components[key] = {
            "platform": "button",
            "name": name,
            "unique_id": f"{PREFIX}_{key}",
            "default_entity_id": f"button.{PREFIX}_{key}",
            "command_topic": f"{ROOT}/command/{key}",
            "payload_press": "PRESS",
            "availability": _availability(),
            "availability_mode": "all",
            "entity_category": "diagnostic",
        }
    return {
        "device": {
            "identifiers": [PREFIX],
            "name": "DigitalHouses Zigbee Monitor App",
            "manufacturer": "DigitalHouses",
            "model": "Zigbee Monitor App",
            "sw_version": version,
        },
        "origin": {
            "name": "DigitalHouses Zigbee Monitor App",
            "sw_version": version,
            "support_url": "https://github.com/DigitalHouses/home-assistant-apps/tree/main/digitalhouses_zigbee_monitor_app",
        },
        "components": components,
    }
