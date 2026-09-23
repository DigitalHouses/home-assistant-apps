"""MQTT Device Discovery payload for DigitalHouses Internet App."""

from __future__ import annotations

from typing import Any

DEVICE_ID = "dh_internet_app"
ENTITY_PREFIX = "dh_internet_app"
MQTT_BASE_TOPIC = "DigitalHouses/Global/dh_internet_app"
DISCOVERY_TOPIC = f"homeassistant/device/{DEVICE_ID}/config"
EVENT_SCHEMA_VERSION = 2

TOPICS = {
    "availability": f"{MQTT_BASE_TOPIC}/availability",
    "state": f"{MQTT_BASE_TOPIC}/state",
    "outages": f"{MQTT_BASE_TOPIC}/outages",
    "event": f"{MQTT_BASE_TOPIC}/event",
    "command": f"{MQTT_BASE_TOPIC}/command",
}


def build_discovery_payload(app_version: str) -> dict[str, Any]:
    availability = {
        "topic": TOPICS["availability"],
        "payload_available": "online",
        "payload_not_available": "offline",
    }
    device = {
        "identifiers": [DEVICE_ID],
        "name": "DigitalHouses Internet App",
        "manufacturer": "DigitalHouses",
        "model": "Internet App",
        "sw_version": app_version,
    }
    components: dict[str, Any] = {
        "internet_status": {
            "platform": "binary_sensor",
            "name": "Internet",
            "unique_id": f"{ENTITY_PREFIX}_internet",
            "default_entity_id": f"binary_sensor.{ENTITY_PREFIX}_internet",
            "device_class": "connectivity",
            "state_topic": TOPICS["state"],
            "value_template": "{{ 'ON' if value_json.internet_up else 'OFF' }}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "availability": availability,
        },
        "router_status": {
            "platform": "binary_sensor",
            "name": "Router",
            "unique_id": f"{ENTITY_PREFIX}_router",
            "default_entity_id": f"binary_sensor.{ENTITY_PREFIX}_router",
            "device_class": "connectivity",
            "state_topic": TOPICS["state"],
            "value_template": "{{ 'ON' if value_json.router_up else 'OFF' }}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "availability": availability,
        },
        "recovery_state": {
            "platform": "sensor",
            "name": "Recovery state",
            "unique_id": f"{ENTITY_PREFIX}_recovery_state",
            "default_entity_id": f"sensor.{ENTITY_PREFIX}_recovery_state",
            "state_topic": TOPICS["state"],
            "value_template": "{{ value_json.recovery.state }}",
            "entity_category": "diagnostic",
            "availability": availability,
        },
        "recovery_cycle": {
            "platform": "sensor",
            "name": "Recovery cycle",
            "unique_id": f"{ENTITY_PREFIX}_recovery_cycle",
            "default_entity_id": f"sensor.{ENTITY_PREFIX}_recovery_cycle",
            "state_topic": TOPICS["state"],
            "value_template": "{{ value_json.recovery.cycle }}",
            "entity_category": "diagnostic",
            "availability": availability,
        },
        "recovery_countdown": {
            "platform": "sensor",
            "name": "Recovery countdown",
            "unique_id": f"{ENTITY_PREFIX}_recovery_countdown",
            "default_entity_id": f"sensor.{ENTITY_PREFIX}_recovery_countdown",
            "state_topic": TOPICS["state"],
            "value_template": "{{ value_json.recovery.countdown_seconds }}",
            "unit_of_measurement": "s",
            "entity_category": "diagnostic",
            "availability": availability,
        },
        "recovery_stop": {
            "platform": "button",
            "name": "Stop recovery",
            "unique_id": f"{ENTITY_PREFIX}_recovery_stop",
            "default_entity_id": f"button.{ENTITY_PREFIX}_recovery_stop",
            "command_topic": TOPICS["command"],
            "payload_press": "STOP_RECOVERY",
            "icon": "mdi:stop-circle-outline",
            "availability": availability,
        },
        "outages_month": {
            "platform": "sensor",
            "name": "Internet outages this month",
            "unique_id": f"{ENTITY_PREFIX}_outages_month",
            "default_entity_id": f"sensor.{ENTITY_PREFIX}_outages_month",
            "state_topic": TOPICS["outages"],
            "value_template": "{{ value_json.state }}",
            "unit_of_measurement": "outages",
            "json_attributes_topic": TOPICS["outages"],
            "json_attributes_template": (
                "{{ {'month': value_json.month, "
                "'outages': value_json.outages, "
                "'total_duration': value_json.total_duration, "
                "'total_duration_seconds': value_json.total_duration_seconds} | tojson }}"
            ),
            "availability": availability,
        },
        "app_version": {
            "platform": "sensor",
            "name": "Version",
            "unique_id": f"{ENTITY_PREFIX}_version",
            "default_entity_id": f"sensor.{ENTITY_PREFIX}_version",
            "state_topic": TOPICS["state"],
            "value_template": "{{ value_json.app_version }}",
            "entity_category": "diagnostic",
            "availability": availability,
        },
        "started_at": {
            "platform": "sensor",
            "name": "Started at",
            "unique_id": f"{ENTITY_PREFIX}_started_at",
            "default_entity_id": f"sensor.{ENTITY_PREFIX}_started_at",
            "state_topic": TOPICS["state"],
            "value_template": "{{ value_json.started_at }}",
            "device_class": "timestamp",
            "entity_category": "diagnostic",
            "availability": availability,
        },
        "event": {
            "platform": "event",
            "name": "Event",
            "unique_id": f"{ENTITY_PREFIX}_event",
            "default_entity_id": f"event.{ENTITY_PREFIX}_event",
            "state_topic": TOPICS["event"],
            "event_types": [
                "connection_lost",
                "connection_restored",
                "recovery_started",
                "recovery_action",
                "recovery_stopped",
                "recovery_exhausted",
                "recovery_error",
            ],
            "value_template": "{{ value_json.event_type }}",
            "json_attributes_topic": TOPICS["event"],
            "availability": availability,
        },
    }
    return {
        "device": device,
        "origin": {
            "name": "DigitalHouses Internet App",
            "sw_version": app_version,
        },
        "components": components,
    }
