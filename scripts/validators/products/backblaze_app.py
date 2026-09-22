from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from validators.common import fail

EXPECTED_BASE_TOPIC = "DigitalHouses/Global/backblaze"
EXPECTED_DEVICE_ID = "digitalhouses_backblaze"
EXPECTED_REFRESH_TOPIC = f"{EXPECTED_BASE_TOPIC}/refresh"


def _import_discovery(app: Path):
    path = app / "rootfs/app/discovery.py"
    spec = importlib.util.spec_from_file_location(
        "digitalhouses_backblaze_discovery_validation",
        path,
    )
    if spec is None or spec.loader is None:
        fail("Unable to import Backblaze discovery.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_backblaze(
    root: Path,
    app: Path,
    context: dict[str, Any],
) -> None:
    del root, context
    discovery = _import_discovery(app)

    if discovery.BASE_TOPIC != EXPECTED_BASE_TOPIC:
        fail("Backblaze MQTT base topic changed")
    if discovery.DEVICE_ID != EXPECTED_DEVICE_ID:
        fail("Backblaze discovery device identifier changed")
    if discovery.REFRESH_COMMAND_TOPIC != EXPECTED_REFRESH_TOPIC:
        fail("Backblaze refresh command topic changed")

    payload = discovery.build_discovery_payload(
        app_version="validation",
        buckets=[{"bucket_id": "bucket-id", "bucket_name": "example-bucket"}],
    )
    components = payload.get("components") or {}

    required_entities = {
        "total_used": "sensor.dh_backblaze_storage_used",
        "bucket_count": "sensor.dh_backblaze_bucket_count",
        "total_files": "sensor.dh_backblaze_files",
        "total_versions": "sensor.dh_backblaze_versions",
        "last_update": "sensor.dh_backblaze_last_update",
        "api_connected": "binary_sensor.dh_backblaze_api",
        "app_version": "sensor.dh_backblaze_app_version",
        "app_started_at": "sensor.dh_backblaze_app_started_at",
        "refresh": "button.dh_backblaze_refresh",
    }
    for key, expected_entity_id in required_entities.items():
        component = components.get(key)
        if not isinstance(component, dict):
            fail(f"Backblaze missing discovery component {key}")
        if component.get("default_entity_id") != expected_entity_id:
            fail(
                f"Backblaze unexpected default_entity_id for {key}: "
                f"{component.get('default_entity_id')!r}"
            )

    started = components["app_started_at"]
    if started.get("device_class") != "timestamp":
        fail("Backblaze started-at diagnostic must use timestamp device class")
    if started.get("entity_category") != "diagnostic":
        fail("Backblaze started-at diagnostic must be diagnostic")
