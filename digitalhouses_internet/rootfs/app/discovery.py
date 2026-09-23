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
        "download": {
            "platform": "sensor",
            "name": "Download",
            "unique_id": f"{ENTITY_PREFIX}_download",
            "default_entity_id": f"sensor.{ENTITY_PREFIX}_download",
            "state_topic": TOPICS["state"],
            "value_template": "{{ value_json.speedtest.download_mbps }}",
            "device_class": "data_rate",
            "state_class": "measurement",
            "unit_of_measurement": "Mbit/s",
            "suggested_display_precision": 1,
            "availability": availability,
        },
        "upload": {
            "platform": "sensor",
            "name": "Upload",
            "unique_id": f"{ENTITY_PREFIX}_upload",
            "default_entity_id": f"sensor.{ENTITY_PREFIX}_upload",
            "state_topic": TOPICS["state"],
            "value_template": "{{ value_json.speedtest.upload_mbps }}",
            "device_class": "data_rate",
            "state_class": "measurement",
            "unit_of_measurement": "Mbit/s",
            "suggested_display_precision": 1,
            "availability": availability,
        },
        "ping": {
            "platform": "sensor",
            "name": "Ping",
            "unique_id": f"{ENTITY_PREFIX}_ping",
            "default_entity_id": f"sensor.{ENTITY_PREFIX}_ping",
            "state_topic": TOPICS["state"],
            "value_template": "{{ value_json.speedtest.ping_ms }}",
            "device_class": "duration",
            "state_class": "measurement",
            "unit_of_measurement": "ms",
            "suggested_display_precision": 1,
            "availability": availability,
        },
        "jitter": {
            "platform": "sensor",
            "name": "Jitter",
            "unique_id": f"{ENTITY_PREFIX}_jitter",
            "default_entity_id": f"sensor.{ENTITY_PREFIX}_jitter",
            "state_topic": TOPICS["state"],
            "value_template": "{{ value_json.speedtest.jitter_ms }}",
            "device_class": "duration",
            "state_class": "measurement",
            "unit_of_measurement": "ms",
            "suggested_display_precision": 1,
            "entity_category": "diagnostic",
            "availability": availability,
        },
        "packet_loss": {
            "platform": "sensor",
            "name": "Packet loss",
            "unique_id": f"{ENTITY_PREFIX}_packet_loss",
            "default_entity_id": f"sensor.{ENTITY_PREFIX}_packet_loss",
            "state_topic": TOPICS["state"],
            "value_template": "{{ value_json.speedtest.packet_loss_pct }}",
            "state_class": "measurement",
            "unit_of_measurement": "%",
            "suggested_display_precision": 1,
            "entity_category": "diagnostic",
            "availability": availability,
        },
        "speedtest_status": {
            "platform": "sensor",
            "name": "Speedtest status",
            "unique_id": f"{ENTITY_PREFIX}_speedtest_status",
            "default_entity_id": f"sensor.{ENTITY_PREFIX}_speedtest_status",
            "state_topic": TOPICS["state"],
            "value_template": "{{ value_json.speedtest.status }}",
            "device_class": "enum",
            "options": [
                "ready",
                "running",
                "success",
                "error",
                "no_connectivity",
            ],
            "json_attributes_topic": TOPICS["state"],
            "json_attributes_template": (
                "{{ {'provider': value_json.speedtest.provider, "
                "'external_ip': value_json.speedtest.external_ip, "
                "'server': value_json.speedtest.server, "
                "'result_url': value_json.speedtest.result_url, "
                "'tested_at': value_json.speedtest.tested_at, "
                "'error': value_json.speedtest.error} | tojson }}"
            ),
            "availability": availability,
        },
        "run_speedtest": {
            "platform": "button",
            "name": "Run speed test",
            "unique_id": f"{ENTITY_PREFIX}_run_speedtest",
            "default_entity_id": f"button.{ENTITY_PREFIX}_run_speedtest",
            "command_topic": TOPICS["command"],
            "payload_press": "RUN_SPEEDTEST",
            "icon": "mdi:speedometer",
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
                "speedtest_completed",
                "speedtest_failed",
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
