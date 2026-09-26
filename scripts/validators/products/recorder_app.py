from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from validators.common import fail, require_files

EXPECTED_BASE_TOPIC = "DigitalHouses/Global/db_monitoring"
EXPECTED_DEVICE_ID = "digitalhouses_db_monitoring"
EXPECTED_REFRESH_TOPIC = f"{EXPECTED_BASE_TOPIC}/refresh"


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

    if config.get("slug") != "digitalhouses_db_monitoring":
        fail(
            f"{app.name}: Recorder 0.1.9 bridge must retain legacy "
            "slug digitalhouses_db_monitoring"
        )

    migration_mode = (config.get("environment") or {}).get(
        "DH_SLUG_MIGRATION_MODE"
    )
    if migration_mode != "export":
        fail(f"{app.name}: Recorder 0.1.9 bridge must use migration export mode")

    mappings = config.get("map") or []
    share_rw = any(
        isinstance(item, dict)
        and item.get("type") == "share"
        and item.get("read_only") is False
        for item in mappings
    )
    if not share_rw:
        fail(f"{app.name}: Recorder migration bridge requires writable share mapping")

    migration_path = app / "rootfs" / "app" / "slug_migration.py"
    require_files(root, [migration_path])
    migration_source = migration_path.read_text(encoding="utf-8")
    for value in (
        'PRODUCT_ID = "digitalhouses_recorder_app"',
        'SOURCE_SLUG = "digitalhouses_db_monitoring"',
        'TARGET_SLUG = "digitalhouses_recorder_app"',
        'BUNDLE_DIR = Path("/share/digitalhouses_recorder_app/slug-migration-v1")',
        '"options.json"',
        '"ssh_known_hosts"',
    ):
        if value not in migration_source:
            fail(f"{app.name}: slug migration contract is missing {value!r}")

    discovery = _import_discovery(app)

    if discovery.BASE_TOPIC != EXPECTED_BASE_TOPIC:
        fail("DB Monitoring MQTT base topic changed")
    if discovery.DEVICE_ID != EXPECTED_DEVICE_ID:
        fail("DB Monitoring discovery device identifier changed")
    if discovery.REFRESH_COMMAND_TOPIC != EXPECTED_REFRESH_TOPIC:
        fail("DB Monitoring refresh command topic changed")

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
