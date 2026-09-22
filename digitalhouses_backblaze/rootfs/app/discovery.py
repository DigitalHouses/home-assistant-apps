"""MQTT Device Discovery for DigitalHouses Backblaze."""

from __future__ import annotations

from typing import Any

from core import slugify

DEVICE_ID = "digitalhouses_global_backblaze"
DEVICE_NAME = "DigitalHouses Backblaze B2"


def _availability(topic: str) -> list[dict[str, str]]:
    return [{
        "topic": topic,
        "payload_available": "online",
        "payload_not_available": "offline",
    }]


def _bucket_entity_slugs(buckets: list[dict[str, Any]]) -> dict[str, str]:
    used: set[str] = set()
    result: dict[str, str] = {}
    for bucket in buckets:
        bucket_id = str(bucket["bucket_id"])
        base = slugify(str(bucket["bucket_name"]))
        slug = base
        if slug in used:
            suffix = slugify(bucket_id[-6:])
            slug = f"{base}_{suffix}"
        used.add(slug)
        result[bucket_id] = slug
    return result


def build_discovery_payload(
    *,
    app_version: str,
    topics: dict[str, str],
    buckets: list[dict[str, Any]],
) -> dict[str, Any]:
    availability = _availability(topics["availability"])
    device = {
        "identifiers": [DEVICE_ID],
        "name": DEVICE_NAME,
        "manufacturer": "DigitalHouses",
        "model": "Backblaze B2 account monitor",
        "sw_version": app_version,
    }
    components: dict[str, Any] = {
        "storage_used": {
            "platform": "sensor",
            "name": "Storage used",
            "unique_id": f"{DEVICE_ID}_storage_used",
            "default_entity_id": "sensor.dh_backblaze_storage_used",
            "state_topic": topics["state"],
            "device_class": "data_size",
            "state_class": "measurement",
            "unit_of_measurement": "GiB",
            "suggested_display_precision": 3,
            "value_template": "{{ value_json.total_gib }}",
            "icon": "mdi:cloud",
            "availability": availability,
        },
        "bucket_count": {
            "platform": "sensor",
            "name": "Buckets",
            "unique_id": f"{DEVICE_ID}_bucket_count",
            "default_entity_id": "sensor.dh_backblaze_bucket_count",
            "state_topic": topics["state"],
            "value_template": "{{ value_json.bucket_count }}",
            "entity_category": "diagnostic",
            "icon": "mdi:bucket-outline",
            "availability": availability,
        },
        "last_update": {
            "platform": "sensor",
            "name": "Last update",
            "unique_id": f"{DEVICE_ID}_last_update",
            "default_entity_id": "sensor.dh_backblaze_last_update",
            "state_topic": topics["state"],
            "value_template": "{{ value_json.last_update }}",
            "device_class": "timestamp",
            "entity_category": "diagnostic",
            "availability": availability,
        },
        "api": {
            "platform": "binary_sensor",
            "name": "API",
            "unique_id": f"{DEVICE_ID}_api",
            "default_entity_id": "binary_sensor.dh_backblaze_api",
            "state_topic": topics["state"],
            "value_template": "{{ 'ON' if value_json.api_ok else 'OFF' }}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "connectivity",
            "entity_category": "diagnostic",
            "availability": availability,
        },
        "app_version": {
            "platform": "sensor",
            "name": "App version",
            "unique_id": f"{DEVICE_ID}_app_version",
            "default_entity_id": "sensor.dh_backblaze_app_version",
            "state_topic": topics["state"],
            "value_template": "{{ value_json.app_version }}",
            "entity_category": "diagnostic",
            "icon": "mdi:tag-outline",
            "availability": availability,
        },
        "app_started_at": {
            "platform": "sensor",
            "name": "App started at",
            "unique_id": f"{DEVICE_ID}_app_started_at",
            "default_entity_id": "sensor.dh_backblaze_app_started_at",
            "state_topic": topics["state"],
            "value_template": "{{ value_json.started_at }}",
            "device_class": "timestamp",
            "entity_category": "diagnostic",
            "availability": availability,
        },
        "refresh": {
            "platform": "button",
            "name": "Refresh",
            "unique_id": f"{DEVICE_ID}_refresh",
            "default_entity_id": "button.dh_backblaze_refresh",
            "command_topic": topics["command"],
            "payload_press": "refresh",
            "entity_category": "config",
            "icon": "mdi:refresh",
            "availability": availability,
        },
    }

    slugs = _bucket_entity_slugs(buckets)
    for bucket in buckets:
        bucket_id = str(bucket["bucket_id"])
        name = str(bucket["bucket_name"])
        slug = slugs[bucket_id]
        prefix = f"bucket_{slug}"
        base_template = f"value_json.buckets['{bucket_id}']"
        components[f"{prefix}_storage"] = {
            "platform": "sensor",
            "name": f"{name} storage",
            "unique_id": f"{DEVICE_ID}_{bucket_id}_storage",
            "default_entity_id": f"sensor.dh_backblaze_{slug}_storage_used",
            "state_topic": topics["state"],
            "device_class": "data_size",
            "state_class": "measurement",
            "unit_of_measurement": "GiB",
            "suggested_display_precision": 3,
            "value_template": "{{ " + base_template + ".storage_gib }}",
            "json_attributes_topic": topics["state"],
            "json_attributes_template": (
                "{{ {'bucket_id': " + base_template + ".bucket_id, "
                "'bucket_type': " + base_template + ".bucket_type, "
                "'storage_bytes': " + base_template + ".storage_bytes, "
                "'old_version_count': " + base_template + ".old_version_count, "
                "'hide_marker_count': " + base_template + ".hide_marker_count} | tojson }}"
            ),
            "icon": "mdi:bucket",
            "availability": availability,
        }
        components[f"{prefix}_files"] = {
            "platform": "sensor",
            "name": f"{name} files",
            "unique_id": f"{DEVICE_ID}_{bucket_id}_files",
            "default_entity_id": f"sensor.dh_backblaze_{slug}_files",
            "state_topic": topics["state"],
            "value_template": "{{ " + base_template + ".file_count }}",
            "entity_category": "diagnostic",
            "icon": "mdi:file-multiple-outline",
            "availability": availability,
        }
        components[f"{prefix}_versions"] = {
            "platform": "sensor",
            "name": f"{name} versions",
            "unique_id": f"{DEVICE_ID}_{bucket_id}_versions",
            "default_entity_id": f"sensor.dh_backblaze_{slug}_versions",
            "state_topic": topics["state"],
            "value_template": "{{ " + base_template + ".version_count }}",
            "entity_category": "diagnostic",
            "icon": "mdi:history",
            "availability": availability,
        }

    return {
        "device": device,
        "origin": {
            "name": "DigitalHouses Backblaze App",
            "sw_version": app_version,
        },
        "components": components,
    }
