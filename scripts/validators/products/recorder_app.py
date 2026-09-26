from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from validators.common import fail, require_files

EXPECTED_BASE_TOPIC = "DigitalHouses/Global/db_monitoring"
EXPECTED_DEVICE_ID = "digitalhouses_db_monitoring"
EXPECTED_REFRESH_TOPIC = f"{EXPECTED_BASE_TOPIC}/refresh"
EXPECTED_EVENT_TOPIC = f"{EXPECTED_BASE_TOPIC}/event/diagnostic"
EXPECTED_THRESHOLD_STATE_TOPIC = (
    f"{EXPECTED_BASE_TOPIC}/settings/disk_usage_threshold_percent/state"
)
EXPECTED_THRESHOLD_COMMAND_TOPIC = (
    f"{EXPECTED_BASE_TOPIC}/settings/disk_usage_threshold_percent/set"
)


def _import_discovery(app: Path):
    path = app / "rootfs/app/discovery.py"
    spec = importlib.util.spec_from_file_location(
        "digitalhouses_db_monitoring_discovery_validation",
        path,
    )
    if spec is None or spec.loader is None:
        fail("Unable to import DB Monitoring discovery.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_db_monitoring(
    root: Path,
    app: Path,
    context: dict[str, Any],
) -> None:
    config = context["config"]

    if config.get("slug") != "digitalhouses_recorder_app":
        fail(
            f"{app.name}: config slug must remain canonical "
            "'digitalhouses_recorder_app'"
        )

    if "DH_SLUG_MIGRATION_MODE" in (config.get("environment") or {}):
        fail(f"{app.name}: completed slug migration mode must be removed")

    mappings = config.get("map") or []
    if any(
        isinstance(item, dict) and item.get("type") == "share"
        for item in mappings
    ):
        fail(f"{app.name}: temporary migration share mapping must be removed")

    migration_path = app / "rootfs" / "app" / "slug_migration.py"
    if migration_path.exists():
        fail(f"{app.name}: completed slug migration runtime must be removed")

    discovery = _import_discovery(app)

    if discovery.BASE_TOPIC != EXPECTED_BASE_TOPIC:
        fail("DB Monitoring MQTT base topic changed")
    if discovery.DEVICE_ID != EXPECTED_DEVICE_ID:
        fail("DB Monitoring discovery device identifier changed")
    if discovery.REFRESH_COMMAND_TOPIC != EXPECTED_REFRESH_TOPIC:
        fail("DB Monitoring refresh command topic changed")
    if discovery.EVENT_TOPIC != EXPECTED_EVENT_TOPIC:
        fail("Recorder diagnostic event topic changed")
    if discovery.DISK_USAGE_THRESHOLD_STATE_TOPIC != EXPECTED_THRESHOLD_STATE_TOPIC:
        fail("Recorder disk threshold state topic changed")
    if discovery.DISK_USAGE_THRESHOLD_COMMAND_TOPIC != EXPECTED_THRESHOLD_COMMAND_TOPIC:
        fail("Recorder disk threshold command topic changed")
    if discovery.EVENT_SCHEMA_VERSION != 2:
        fail("Recorder diagnostic event schema version must be 2")

    payload = discovery.build_discovery_payload(
        app_version="validation",
        include_storage=True,
    )
    components = payload.get("components") or {}
    required_entities = {
        "db_start": "sensor.dh_db_start",
        "db_connected": "binary_sensor.dh_db_connected",
        "recorder_writing": "binary_sensor.dh_db_recorder_writing",
        "db_last_refresh": "sensor.dh_db_last_refresh",
        "db_top_entities_24h": "sensor.dh_db_top_entities_24h",
        "db_top_entities_all_time": "sensor.dh_db_top_entities_all_time",
        "db_refresh": "button.dh_db_refresh",
        "db_disk_free": "sensor.dh_db_disk_free",
        "db_disk_used": "sensor.dh_db_disk_used",
        "db_disk_total": "sensor.dh_db_disk_total",
        "db_disk_used_percentage": "sensor.dh_db_disk_used_percentage",
        "db_disk_usage_threshold": "number.dh_db_disk_usage_threshold",
        "diagnostic_event": "event.dh_db_diagnostic",
    }
    for key, expected_entity_id in required_entities.items():
        component = components.get(key)
        if not isinstance(component, dict):
            fail(f"DB Monitoring missing discovery component {key}")
        if component.get("default_entity_id") != expected_entity_id:
            fail(
                f"DB Monitoring unexpected default_entity_id for {key}: "
                f"{component.get('default_entity_id')!r}"
            )


    event_component = components["diagnostic_event"]
    if event_component.get("platform") != "event":
        fail("Recorder diagnostic entity must use MQTT event platform")
    expected_event_types = {
        "db_connection_lost",
        "db_connection_restored",
        "recorder_writing_stopped",
        "recorder_writing_restored",
        "storage_usage_high",
        "storage_usage_normal",
    }
    if set(event_component.get("event_types") or []) != expected_event_types:
        fail("Recorder diagnostic event types changed")

    threshold_component = components["db_disk_usage_threshold"]
    if threshold_component.get("platform") != "number":
        fail("Recorder disk usage threshold must be an MQTT number")
    if threshold_component.get("min") != 1 or threshold_component.get("max") != 98:
        fail("Recorder disk usage threshold range must remain 1..98")
