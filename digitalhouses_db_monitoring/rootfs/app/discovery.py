from __future__ import annotations

from typing import Any

DEVICE_ID = "digitalhouses_db_monitoring"
DEVICE_NAME = "DH Recorder Database"
BASE_TOPIC = "DigitalHouses/Global/db_monitoring"
STATE_TOPIC = f"{BASE_TOPIC}/state"
APP_AVAILABILITY_TOPIC = f"{BASE_TOPIC}/availability"
DB_AVAILABILITY_TOPIC = f"{BASE_TOPIC}/database_availability"
DISCOVERY_TOPIC = f"homeassistant/device/{DEVICE_ID}/config"
HA_STATUS_TOPIC = "homeassistant/status"


def _availability(topic: str) -> dict[str, str]:
    return {
        "topic": topic,
        "payload_available": "online",
        "payload_not_available": "offline",
    }


def _component(
    platform: str,
    name: str,
    unique_suffix: str,
    entity_id: str,
    value_template: str,
    *,
    diagnostic: bool = False,
    db_required: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    availability = [_availability(APP_AVAILABILITY_TOPIC)]
    if db_required:
        availability.append(_availability(DB_AVAILABILITY_TOPIC))
    payload: dict[str, Any] = {
        "platform": platform,
        "name": name,
        "unique_id": f"{DEVICE_ID}_{unique_suffix}",
        "default_entity_id": entity_id,
        "state_topic": STATE_TOPIC,
        "value_template": value_template,
        "availability": availability,
        "availability_mode": "all",
    }
    if diagnostic:
        payload["entity_category"] = "diagnostic"
    payload.update(extra)
    return payload


def build_discovery_payload(app_version: str) -> dict[str, Any]:
    components = {
        "db_start": _component(
            "sensor", "Database start", "db_start", "sensor.dh_db_start",
            "{{ value_json.db_start }}", diagnostic=True,
            device_class="timestamp", icon="mdi:database-clock-outline",
        ),
        "db_last": _component(
            "sensor", "Database last record", "db_last", "sensor.dh_db_last",
            "{{ value_json.db_last }}", diagnostic=True,
            device_class="timestamp", icon="mdi:database-clock",
        ),
        "db_depth": _component(
            "sensor", "Database history depth", "db_depth", "sensor.dh_db_depth",
            "{{ value_json.db_depth }}", diagnostic=True,
            device_class="duration", state_class="measurement",
            unit_of_measurement="d", icon="mdi:calendar-range",
        ),
        "db_records_per_hour": _component(
            "sensor", "Records per hour", "db_records_per_hour", "sensor.dh_db_records_per_hour",
            "{{ value_json.db_records_per_hour }}", diagnostic=True,
            state_class="measurement", unit_of_measurement="k rec/h", icon="mdi:database-arrow-down",
        ),
        "db_records": _component(
            "sensor", "Database records", "db_records", "sensor.dh_db_records",
            "{{ value_json.db_records }}", diagnostic=True,
            state_class="measurement", unit_of_measurement="k records", icon="mdi:database-marker",
        ),
        "db_size": _component(
            "sensor", "Database size", "db_size", "sensor.dh_db_size",
            "{{ value_json.db_size }}", diagnostic=True,
            device_class="data_size", state_class="measurement",
            unit_of_measurement="MiB", suggested_display_precision=1, icon="mdi:database",
        ),
        "db_version": _component(
            "sensor", "Database version", "db_version", "sensor.dh_db_version",
            "{{ value_json.db_version }}", diagnostic=True, icon="mdi:database-cog",
        ),
        "db_yesterday_records": _component(
            "sensor", "Yesterday records", "db_yesterday_records", "sensor.dh_db_yesterday_records",
            "{{ value_json.db_yesterday_records }}", diagnostic=True,
            state_class="measurement", unit_of_measurement="records", icon="mdi:calendar-arrow-left",
        ),
        "db_name": _component(
            "sensor", "Database name", "db_name", "sensor.dh_db_name",
            "{{ value_json.db_name }}", diagnostic=True, icon="mdi:database-settings",
        ),
        "db_user": _component(
            "sensor", "Database user", "db_user", "sensor.dh_db_user",
            "{{ value_json.db_user }}", diagnostic=True, icon="mdi:account-key",
        ),
        "db_connected": _component(
            "binary_sensor", "Database connected", "db_connected", "binary_sensor.dh_db_connected",
            "{{ 'ON' if value_json.db_connected else 'OFF' }}", diagnostic=True, db_required=False,
            device_class="connectivity",
        ),
        "recorder_writing": _component(
            "binary_sensor", "Recorder writing", "recorder_writing", "binary_sensor.dh_recorder_writing",
            "{{ 'ON' if value_json.recorder_writing else 'OFF' }}", diagnostic=True, db_required=False,
            icon="mdi:database-edit",
        ),
        "db_last_age": _component(
            "sensor", "Last record age", "db_last_age", "sensor.dh_db_last_age",
            "{{ value_json.db_last_age }}", diagnostic=True,
            device_class="duration", state_class="measurement", unit_of_measurement="s",
            icon="mdi:timer-sand",
        ),
    }
    return {
        "device": {
            "identifiers": [DEVICE_ID],
            "name": DEVICE_NAME,
            "manufacturer": "DigitalHouses",
            "model": "Home Assistant Recorder Database Monitor",
            "sw_version": app_version,
        },
        "origin": {
            "name": "DigitalHouses DB Monitoring",
            "sw_version": app_version,
            "support_url": "https://github.com/DigitalHouses/home-assistant-apps/tree/main/digitalhouses_db_monitoring",
        },
        "components": components,
    }
