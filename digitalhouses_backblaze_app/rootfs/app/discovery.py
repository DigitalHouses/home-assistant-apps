from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

DEVICE_ID = "digitalhouses_backblaze"
DEVICE_NAME = "DH Backblaze"
BASE_TOPIC = "DigitalHouses/Global/backblaze"
STATE_TOPIC = f"{BASE_TOPIC}/state"
STORAGE_TREE_TOPIC = f"{BASE_TOPIC}/storage_tree"
REFRESH_OPERATION_TOPIC = f"{BASE_TOPIC}/refresh/operation"
APP_AVAILABILITY_TOPIC = f"{BASE_TOPIC}/availability"
DATA_AVAILABILITY_TOPIC = f"{BASE_TOPIC}/data_availability"
API_OBSERVED_TOPIC = f"{BASE_TOPIC}/api_observed"
DISCOVERY_TOPIC = f"homeassistant/device/{DEVICE_ID}/config"
REFRESH_COMMAND_TOPIC = f"{BASE_TOPIC}/refresh"
TELEMETRY_DELETE_COMMAND_TOPIC = f"{BASE_TOPIC}/telemetry/delete"
HA_STATUS_TOPIC = "homeassistant/status"
STATE_RETAIN = True
DISCOVERY_SCHEMA_VERSION = 4
DISCOVERY_SCHEMA_PATH = Path("/data/discovery_schema_version")
DISCOVERY_MANIFEST_SCHEMA_VERSION = 1
DISCOVERY_MANIFEST_PATH = Path("/data/discovery_manifest.json")


def needs_discovery_reset(path: Path = DISCOVERY_SCHEMA_PATH) -> bool:
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return True
    return value < DISCOVERY_SCHEMA_VERSION


def mark_discovery_schema(path: Path = DISCOVERY_SCHEMA_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(str(DISCOVERY_SCHEMA_VERSION), encoding="utf-8")
    tmp.replace(path)


def bucket_state_topic(bucket_id: str) -> str:
    return f"{BASE_TOPIC}/bucket/{bucket_id}/state"


def bucket_slug(bucket_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", bucket_name.lower()).strip("_")
    return slug or "bucket"


def _availability(*, data_required: bool = False, api_observed: bool = False) -> list[dict[str, str]]:
    items = [{
        "topic": APP_AVAILABILITY_TOPIC,
        "payload_available": "online",
        "payload_not_available": "offline",
    }]
    if data_required:
        items.append({
            "topic": DATA_AVAILABILITY_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
        })
    if api_observed:
        items.append({
            "topic": API_OBSERVED_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
        })
    return items


def _component(
    platform: str,
    name: str,
    unique_suffix: str,
    entity_id: str,
    value_template: str,
    *,
    state_topic: str = STATE_TOPIC,
    diagnostic: bool = False,
    data_required: bool = False,
    api_observed: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "platform": platform,
        "name": name,
        "unique_id": f"{DEVICE_ID}_{unique_suffix}",
        "default_entity_id": entity_id,
        "state_topic": state_topic,
        "value_template": value_template,
        "availability": _availability(
            data_required=data_required,
            api_observed=api_observed,
        ),
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
    *,
    removed_buckets: Iterable[dict[str, str]] = (),
) -> dict[str, Any]:
    components: dict[str, dict[str, Any]] = {
        "total_used": _component(
            "sensor",
            "Total used",
            "total_used",
            "sensor.dh_backblaze_storage_used",
            "{{ (value_json.stored_bytes / 1073741824) | round(1) }}",
            data_required=True,
            device_class="data_size",
            state_class="measurement",
            unit_of_measurement="GiB",
            suggested_display_precision=1,
            icon="mdi:cloud-outline",
        ),
        "bucket_count": _component(
            "sensor",
            "Buckets",
            "bucket_count",
            "sensor.dh_backblaze_bucket_count",
            "{{ value_json.bucket_count }}",
            data_required=True,
            state_class="measurement",
            icon="mdi:bucket-outline",
        ),
        "total_files": _component(
            "sensor",
            "Total files",
            "total_files",
            "sensor.dh_backblaze_files",
            "{{ value_json.current_files }}",
            data_required=True,
            state_class="measurement",
            icon="mdi:file-multiple-outline",
        ),
        "total_versions": _component(
            "sensor",
            "Stored versions",
            "total_versions",
            "sensor.dh_backblaze_versions",
            "{{ value_json.versions }}",
            data_required=True,
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
            data_required=True,
            device_class="timestamp",
            icon="mdi:cloud-sync-outline",
        ),
        "storage_tree": _component(
            "sensor",
            "Storage tree",
            "storage_tree",
            "sensor.dh_backblaze_storage_tree",
            "{{ value_json.folder_count }}",
            state_topic=STORAGE_TREE_TOPIC,
            data_required=True,
            state_class="measurement",
            icon="mdi:file-tree-outline",
            json_attributes_topic=STORAGE_TREE_TOPIC,
            json_attributes_template=(
                "{{ {'generated_at': value_json.generated_at | default(none), "
                "'buckets': value_json.buckets | default([])} | tojson }}"
            ),
        ),
        "last_refresh": _component(
            "sensor",
            "Last refresh",
            "last_refresh",
            "sensor.dh_backblaze_last_refresh",
            "{{ value_json.last_refresh }}",
            diagnostic=True,
            device_class="timestamp",
            icon="mdi:clock-check-outline",
        ),
        "refresh_state": _component(
            "sensor",
            "Refresh state",
            "refresh_state",
            "sensor.dh_backblaze_refresh_state",
            "{{ value_json.state | default('idle') }}",
            state_topic=REFRESH_OPERATION_TOPIC,
            diagnostic=True,
            icon="mdi:progress-clock",
            json_attributes_topic=REFRESH_OPERATION_TOPIC,
            json_attributes_template=(
                "{{ {'started_at': value_json.started_at | default(none), "
                "'finished_at': value_json.finished_at | default(none), "
                "'duration_seconds': value_json.duration_seconds | default(none), "
                "'error': value_json.error | default(none)} | tojson }}"
            ),
        ),
        "api_connected": _component(
            "binary_sensor",
            "API",
            "api_connected",
            "binary_sensor.dh_backblaze_api",
            "{{ 'ON' if value_json.api_connected else 'OFF' }}",
            diagnostic=True,
            api_observed=True,
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

    active_bucket_ids: set[str] = set()
    for bucket in buckets:
        bucket_id = str(bucket["bucket_id"])
        bucket_name = str(bucket["bucket_name"])
        active_bucket_ids.add(bucket_id)
        slug = bucket_slug(bucket_name)
        topic = bucket_state_topic(bucket_id)
        prefix = f"bucket_{bucket_id}"

        components[f"{prefix}_used"] = _component(
            "sensor",
            f"{bucket_name} used",
            f"{prefix}_used",
            f"sensor.dh_backblaze_{slug}_used",
            "{{ (value_json.stored_bytes / 1073741824) | round(1) }}",
            state_topic=topic,
            data_required=True,
            device_class="data_size",
            state_class="measurement",
            unit_of_measurement="GiB",
            suggested_display_precision=1,
            icon="mdi:bucket-outline",
        )
        components[f"{prefix}_files"] = _component(
            "sensor",
            f"{bucket_name} files",
            f"{prefix}_files",
            f"sensor.dh_backblaze_{slug}_files",
            "{{ value_json.current_files }}",
            state_topic=topic,
            data_required=True,
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
            data_required=True,
            state_class="measurement",
            icon="mdi:file-clock-outline",
        )

    for bucket in removed_buckets:
        bucket_id = str(bucket["bucket_id"])
        if bucket_id in active_bucket_ids:
            continue
        prefix = f"bucket_{bucket_id}"
        components[f"{prefix}_used"] = {"platform": "sensor"}
        components[f"{prefix}_files"] = {"platform": "sensor"}
        components[f"{prefix}_versions"] = {"platform": "sensor"}

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
                "tree/main/digitalhouses_backblaze_app"
            ),
        },
        "components": components,
    }


def dynamic_discovery_manifest(
    payload: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    raw_components = payload.get("components")
    if not isinstance(raw_components, Mapping):
        raise ValueError("Discovery payload has no components mapping")

    manifest: dict[str, dict[str, Any]] = {}
    for key, component in raw_components.items():
        if not str(key).startswith("bucket_"):
            continue
        if not isinstance(component, Mapping):
            raise ValueError(f"Discovery component {key!r} is not a mapping")
        platform = component.get("platform")
        state_topic = component.get("state_topic")
        if not isinstance(platform, str) or not platform:
            raise ValueError(f"Discovery component {key!r} has no platform")
        if not isinstance(state_topic, str) or not state_topic:
            raise ValueError(f"Discovery component {key!r} has no state_topic")
        manifest[str(key)] = {
            "platform": platform,
            "topics": [state_topic],
        }
    return manifest


def removed_discovery_components(
    previous: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, str], tuple[str, ...]]:
    removals: dict[str, str] = {}
    candidate_topics: set[str] = set()

    for key, item in previous.items():
        if key in current:
            continue
        platform = item.get("platform")
        topics = item.get("topics")
        if not isinstance(platform, str) or not platform:
            raise ValueError(f"Discovery manifest component {key!r} has invalid platform")
        if not isinstance(topics, list):
            raise ValueError(f"Discovery manifest component {key!r} has invalid topics")
        removals[str(key)] = platform
        candidate_topics.update(
            topic for topic in topics if isinstance(topic, str) and topic
        )

    current_topics = {
        topic
        for item in current.values()
        for topic in item.get("topics", [])
        if isinstance(topic, str) and topic
    }
    return removals, tuple(sorted(candidate_topics - current_topics))


def discovery_cleanup_payload(
    payload: Mapping[str, Any],
    removals: Mapping[str, str],
) -> dict[str, Any]:
    cleanup = dict(payload)
    raw_components = payload.get("components")
    components = dict(raw_components) if isinstance(raw_components, Mapping) else {}
    for key, platform in removals.items():
        components[str(key)] = {"platform": str(platform)}
    cleanup["components"] = components
    return cleanup


def load_discovery_manifest(
    path: Path = DISCOVERY_MANIFEST_PATH,
) -> dict[str, dict[str, Any]] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read discovery manifest: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("Discovery manifest must be an object")
    if raw.get("schema_version") != DISCOVERY_MANIFEST_SCHEMA_VERSION:
        raise ValueError("Unsupported discovery manifest schema")
    components = raw.get("components")
    if not isinstance(components, dict):
        raise ValueError("Discovery manifest components must be an object")

    normalized: dict[str, dict[str, Any]] = {}
    for key, item in components.items():
        if not isinstance(key, str) or not isinstance(item, dict):
            raise ValueError("Discovery manifest component is malformed")
        platform = item.get("platform")
        topics = item.get("topics")
        if not isinstance(platform, str) or not platform:
            raise ValueError(f"Discovery manifest component {key!r} has invalid platform")
        if (
            not isinstance(topics, list)
            or not all(isinstance(topic, str) and topic for topic in topics)
        ):
            raise ValueError(f"Discovery manifest component {key!r} has invalid topics")
        normalized[key] = {
            "platform": platform,
            "topics": sorted(set(topics)),
        }
    return normalized


def save_discovery_manifest(
    components: Mapping[str, Mapping[str, Any]],
    path: Path = DISCOVERY_MANIFEST_PATH,
) -> None:
    payload = {
        "schema_version": DISCOVERY_MANIFEST_SCHEMA_VERSION,
        "components": {
            str(key): {
                "platform": str(item["platform"]),
                "topics": sorted(
                    {
                        str(topic)
                        for topic in item.get("topics", [])
                        if isinstance(topic, str) and topic
                    }
                ),
            }
            for key, item in sorted(components.items())
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp.replace(path)
