"""Home Assistant MQTT Device Discovery for the read-only Zigbee Monitor.

Recorder-facing scalars never expose dynamic JSON attributes. Rich UI snapshots
are separate entities and MUST be excluded from the site's Recorder policy.
"""
from __future__ import annotations

from typing import Any

from .core import Network
from .problems import PROBLEM_TYPES

PRODUCT = "digitalhouses_zigbee_monitor_app"
PREFIX = "dh_zigbee_monitor_app"
ROOT = "DigitalHouses/Global/dh_zigbee_monitor_app"
DISCOVERY = f"homeassistant/device/{PREFIX}/config"
APP_AVAILABILITY = f"{ROOT}/availability"
HA_STATUS = "homeassistant/status"
EVENT_TOPIC = f"{ROOT}/event"
EVENT_TYPES = (
    "device_offline", "device_online",
    "zigbee2mqtt_offline", "zigbee2mqtt_online",
    "problem_started", "problem_recovered",
)

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
    "repeaters_details": "repeaters",
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


def build_discovery(version: str, networks: tuple[Network, ...] = ()) -> dict[str, Any]:
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
    # Transient machine events: non-retained QoS 1 publications from App.
    # The MQTT Event entity itself is excluded from the HA Recorder policy.
    components["event"] = _component(
        "event", "event", "Zigbee Monitor machine events",
        state_topic=EVENT_TOPIC, event_types=list(EVENT_TYPES),
        icon="mdi:alert-network-outline",
        entity_category="diagnostic",
    )
    # Fixed-path, read-only mount diagnostic; no Zigbee2MQTT secrets or raw YAML.
    components["config_access"] = _component(
        "sensor", "config_access", "HA configuration file access",
        value_template="{{ value_json.state }}",
        json_attributes_topic=state_topic("config_access"),
        entity_category="diagnostic",
        icon="mdi:folder-search-outline",
    )
    components["refresh_state"] = _component(
        "sensor", "refresh_state", "Refresh state",
        value_template="{{ value_json.state }}",
        json_attributes_topic=state_topic("refresh_state"),
        entity_category="diagnostic",
        icon="mdi:refresh",
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
    # One stable discovery component set per automatically discovered network.
    # All controls and problem flags are owned by this App, never HA helpers.
    for network in networks:
        nid = network.network_id
        for kind in PROBLEM_TYPES:
            key = f"{nid}_{kind}_problem"
            valid = f"{ROOT}/problems/{nid}/{kind}/valid"
            components[key] = {
                "platform": "binary_sensor",
                "name": f"{network.name}: {kind.replace('_', ' ')}",
                "unique_id": f"{PREFIX}_{key}",
                "default_entity_id": f"binary_sensor.{PREFIX}_{key}",
                "state_topic": f"{ROOT}/problems/{nid}/{kind}/state",
                "payload_on": "ON", "payload_off": "OFF",
                "availability": _availability() + [{
                    "topic": valid,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                }],
                "availability_mode": "all",
                "device_class": "problem",
                "entity_category": "diagnostic",
            }
        components[f"{nid}_rpm_auto"] = {
            "platform": "switch",
            "name": f"{network.name}: automatic RPM threshold",
            "unique_id": f"{PREFIX}_{nid}_rpm_auto",
            "default_entity_id": f"switch.{PREFIX}_{nid}_rpm_auto",
            "state_topic": f"{ROOT}/settings/{nid}/rpm_auto/state",
            "command_topic": f"{ROOT}/command/settings/{nid}/rpm_auto",
            "payload_on": "ON", "payload_off": "OFF",
            "availability": _availability(),
            "entity_category": "config",
            "icon": "mdi:tune-auto",
        }
        components[f"{nid}_rpm_threshold"] = {
            "platform": "number",
            "name": f"{network.name}: manual RPM threshold",
            "unique_id": f"{PREFIX}_{nid}_rpm_threshold",
            "default_entity_id": f"number.{PREFIX}_{nid}_rpm_threshold",
            "state_topic": f"{ROOT}/settings/{nid}/rpm_threshold/state",
            "command_topic": f"{ROOT}/command/settings/{nid}/rpm_threshold",
            "min": 1, "max": 10000, "step": 1,
            "unit_of_measurement": "messages/min",
            "availability": _availability(),
            "entity_category": "config",
            "icon": "mdi:speedometer-slow",
        }
    components["problems"] = {
        "platform": "sensor", "name": "Zigbee problems",
        "unique_id": f"{PREFIX}_problems",
        "default_entity_id": f"sensor.{PREFIX}_problems",
        "state_topic": f"{ROOT}/problems/aggregate",
        "availability": _availability() + [{
            "topic": f"{ROOT}/problems/valid",
            "payload_available": "online",
            "payload_not_available": "offline",
        }],
        "availability_mode": "all",
        "json_attributes_topic": f"{ROOT}/problems/presentation",
        "entity_category": "diagnostic",
        "icon": "mdi:alert-circle-outline",
    }
    components["delete_telemetry"] = {
        "platform": "button",
        "name": "Delete DigitalHouses telemetry",
        "unique_id": f"{PREFIX}_delete_telemetry",
        "default_entity_id": f"button.{PREFIX}_delete_telemetry",
        "command_topic": f"{ROOT}/command/delete_telemetry",
        "payload_press": "DELETE",
        "availability": _availability(),
        "availability_mode": "all",
        "entity_category": "config",
        "icon": "mdi:database-remove",
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
