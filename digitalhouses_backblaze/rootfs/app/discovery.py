from __future__ import annotations

import re
from typing import Any, Iterable

DEVICE_ID = "digitalhouses_backblaze"
DEVICE_NAME = "DH Backblaze"
BASE_TOPIC = "DigitalHouses/Global/backblaze"
STATE_TOPIC = f"{BASE_TOPIC}/state"
APP_AVAILABILITY_TOPIC = f"{BASE_TOPIC}/availability"
DISCOVERY_TOPIC = f"homeassistant/device/{DEVICE_ID}/config"
REFRESH_COMMAND_TOPIC = f"{BASE_TOPIC}/refresh"
TELEMETRY_DELETE_COMMAND_TOPIC = f"{BASE_TOPIC}/telemetry/delete"
HA_STATUS_TOPIC = "homeassistant/status"
STATE_RETAIN = True


def bucket_state_topic(bucket_id: str) -> str:
    return f"{BASE_TOPIC}/bucket/{bucket_id}/state"


def bucket_slug(bucket_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", bucket_name.lower()).strip("_")
    return slug or "bucket"


def _availability() -> list[dict[str, str]]:
    return [{
        "topic": APP_AVAILABILITY_TOPIC,
        "payload_available": "online",
        "payload_not_available": "offline",
    }]


def _component(
    platform: str,
    name: str,
    unique_suffix: str,
    entity_id: str,
    value_template: str,
    *,
    state_topic: str = STATE_TOPIC,
    diagnostic: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "platform": platform,
        "name": name,
        "unique_id": f"{DEVICE_ID}_{unique_suffix}",
        "default_entity_id": entity_id,
        "state_topic": state_topic,
        "value_template": value_template,
        "availability": _availability(),
        "availability_mode": "all",
    }
    if diagnostic:
        payload["entity_category"] = "diagnostic"
    payload.update(extra)
    return payload


def _button(
    name: str,
    unique_suffix: str,
    entity_id: str,
    command_topic: str,
    *,
    icon: str = "mdi:refresh",
    entity_category: str = "config",
) -> dict[str, Any]:
    return {
        "platform": "button",
        "name": name,
        "unique_id": f"{DEVICE_ID}_{unique_suffix}",
        "default_entity_id": entity_id,
        "command_topic": command_topic,
        "payload_press": "PRESS",
        "availability": _availability(),
        "availability_mode": "all",
        "entity_category": entity_category,
        "icon": icon,
    }


def build_discovery_payload(
    app_version: str,
    buckets: Iterable[dict[str, str]] = (),
) -> dict[str, Any]:
    components: dict[str, dict[str, Any]] = {
        "total_used": _component(
            "sensor",
            "Storage used",
            "total_used",
            "sensor.dh_backblaze_storage_used",
            "{{ value_json.stored_bytes }}",
            device_class="data_size",
            state_class="measurement",
            unit_of_measurement="B",
            suggested_display_precision=1,
            icon="mdi:cloud-outline",
        ),
        "bucket_count": _component(
            "sensor",
            "Buckets",
            "bucket_count",
            "sensor.dh_backblaze_bucket_count",
            "{{ value_json.bucket_count }}",
            state_class="measurement",
            icon="mdi:bucket-outline",
        ),
        "total_files": _component(
            "sensor",
            "Current files",
            "total_files",
            "sensor.dh_backblaze_files",
            "{{ value_json.current_files }}",
            state_class="measurement",
            icon="mdi:file-multiple-outline",
        ),
        "total_versions": _component(
            "sensor",
            "Stored versions",
            "total_versions",
            "sensor.dh_backblaze_versions",
            "{{ value_json.versions }}",
            state_class="measurement",
            icon="mdi:file-clock-outline",
        ),
        "last_update": _component(
            "sensor",
            "Last update",
            "last_update",
            "sensor.dh_backblaze_last_update",
            "{{ value_json.last_update }}",
            diagnostic=True,
            device_class="timestamp",
            icon="mdi:cloud-sync-outline",
        ),
        "api_connected": _component(
            "binary_sensor",
            "API",
            "api_connected",
            "binary_sensor.dh_backblaze_api",
            "{{ 'ON' if value_json.api_connected else 'OFF' }}",
            diagnostic=True,
            device_class="connectivity",
        ),
        "app_version": _component(
            "sensor",
            "App version",
            "app_version",
            "sensor.dh_backblaze_app_version",
            "{{ value_json.app_version }}",
            diagnostic=True,
            icon="mdi:tag-outline",
        ),
        "app_started_at": _component(
            "sensor",
            "Started at",
            "app_started_at",
            "sensor.dh_backblaze_app_started_at",
            "{{ value_json.app_started_at }}",
            diagnostic=True,
            device_class="timestamp",
            icon="mdi:clock-start",
        ),
        "refresh": _button(
            "Refresh",
            "refresh",
            "button.dh_backblaze_refresh",
            REFRESH_COMMAND_TOPIC,
        ),
        "telemetry_delete": _button(
            "Delete telemetry data",
            "telemetry_delete",
            "button.dh_backblaze_delete_telemetry",
            TELEMETRY_DELETE_COMMAND_TOPIC,
            icon="mdi:database-remove-outline",
            entity_category="config",
        ),
    }

    for bucket in buckets:
        bucket_id = str(bucket["bucket_id"])
        bucket_name = str(bucket["bucket_name"])
        slug = bucket_slug(bucket_name)
        topic = bucket_state_topic(bucket_id)
        prefix = f"bucket_{bucket_id}"

        components[f"{prefix}_used"] = _component(
            "sensor",
            f"{bucket_name} used",
            f"{prefix}_used",
            f"sensor.dh_backblaze_{slug}_used",
            "{{ value_json.stored_bytes }}",
            state_topic=topic,
            device_class="data_size",
            state_class="measurement",
            unit_of_measurement="B",
            suggested_display_precision=1,
            icon="mdi:bucket-outline",
            json_attributes_topic=topic,
        )
        components[f"{prefix}_files"] = _component(
            "sensor",
            f"{bucket_name} files",
            f"{prefix}_files",
            f"sensor.dh_backblaze_{slug}_files",
            "{{ value_json.current_files }}",
            state_topic=topic,
            state_class="measurement",
            icon="mdi:file-multiple-outline",
        )
        components[f"{prefix}_versions"] = _component(
            "sensor",
            f"{bucket_name} versions",
            f"{prefix}_versions",
            f"sensor.dh_backblaze_{slug}_versions",
            "{{ value_json.versions }}",
            state_topic=topic,
            state_class="measurement",
            icon="mdi:file-clock-outline",
        )

    return {
        "device": {
            "identifiers": [DEVICE_ID],
            "name": DEVICE_NAME,
            "manufacturer": "DigitalHouses",
            "model": "Backblaze B2 Storage Monitor",
            "sw_version": app_version,
        },
        "origin": {
            "name": "DigitalHouses Backblaze",
            "sw_version": app_version,
            "support_url": (
                "https://github.com/DigitalHouses/home-assistant-apps/"
                "tree/main/digitalhouses_backblaze"
            ),
        },
        "components": components,
    }
