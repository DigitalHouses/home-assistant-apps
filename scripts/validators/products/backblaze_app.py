from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from validators.common import fail, require_files

EXPECTED_TOPIC = "DigitalHouses/Global/backblaze"
EXPECTED_DEVICE_ID = "digitalhouses_global_backblaze"
EXPECTED_RELEASE_PRODUCT = "digitalhouses_backblaze_app"


def _import_module(app: Path, name: str):
    path = app / f"rootfs/app/{name}.py"
    spec = importlib.util.spec_from_file_location(
        f"digitalhouses_backblaze_{name}_validation",
        path,
    )
    if spec is None or spec.loader is None:
        fail(f"Unable to import Backblaze {name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_backblaze(root: Path, app: Path, context: dict[str, Any]) -> None:
    require_files(
        root,
        [
            app / "rootfs/app/app.py",
            app / "rootfs/app/backblaze.py",
            app / "rootfs/app/config.py",
            app / "rootfs/app/core.py",
            app / "rootfs/app/discovery.py",
            app / "rootfs/app/telemetry.py",
        ],
    )

    config = context["config"]
    options = config.get("options") or {}
    schema = config.get("schema") or {}

    if config.get("stage") != "experimental":
        fail("Backblaze App must remain experimental during foundation phase")
    if options.get("refresh_interval_hours") != 6:
        fail("Backblaze refresh interval default must remain 6 hours")
    if options.get("telemetry_enabled") is not False:
        fail("Backblaze telemetry must be disabled by default")
    for key in (
        "application_key_id",
        "application_key",
        "refresh_interval_hours",
        "telemetry_enabled",
    ):
        if key not in schema:
            fail(f"Backblaze config schema is missing {key}")

    app_source = (app / "rootfs/app/app.py").read_text(encoding="utf-8")
    if f'MQTT_BASE_TOPIC = "{EXPECTED_TOPIC}"' not in app_source:
        fail("Backblaze MQTT base topic changed")

    backblaze_source = (app / "rootfs/app/backblaze.py").read_text(encoding="utf-8")
    if "/b2api/v4/b2_authorize_account" not in backblaze_source:
        fail("Backblaze client must use Native API v4 authorization")
    if "maxFileCount" not in backblaze_source or "1000" not in backblaze_source:
        fail("Backblaze file-version pagination contract is missing")

    telemetry_source = (app / "rootfs/app/telemetry.py").read_text(encoding="utf-8")
    if f'PRODUCT = "{EXPECTED_RELEASE_PRODUCT}"' not in telemetry_source:
        fail("Backblaze telemetry product identifier changed")

    discovery = _import_module(app, "discovery")
    if discovery.DEVICE_ID != EXPECTED_DEVICE_ID:
        fail("Backblaze Discovery device identifier changed")

    payload = discovery.build_discovery_payload(
        app_version=context["version"],
        topics={
            "state": f"{EXPECTED_TOPIC}/state",
            "command": f"{EXPECTED_TOPIC}/command",
            "availability": f"{EXPECTED_TOPIC}/availability",
        },
        buckets=[],
    )
    components = payload.get("components") or {}

    expected = {
        "storage_used": "sensor.dh_backblaze_storage_used",
        "bucket_count": "sensor.dh_backblaze_bucket_count",
        "last_update": "sensor.dh_backblaze_last_update",
        "api": "binary_sensor.dh_backblaze_api",
        "app_version": "sensor.dh_backblaze_app_version",
        "app_started_at": "sensor.dh_backblaze_app_started_at",
        "refresh": "button.dh_backblaze_refresh",
    }
    for key, entity_id in expected.items():
        component = components.get(key)
        if not isinstance(component, dict):
            fail(f"Backblaze missing discovery component {key}")
        if component.get("default_entity_id") != entity_id:
            fail(f"Backblaze entity ID changed for {key}")

    if components["app_version"].get("entity_category") != "diagnostic":
        fail("Backblaze App version must be diagnostic")
    started = components["app_started_at"]
    if started.get("entity_category") != "diagnostic":
        fail("Backblaze App started-at must be diagnostic")
    if started.get("device_class") != "timestamp":
        fail("Backblaze App started-at must use timestamp device class")

    if payload.get("device", {}).get("sw_version") != context["version"]:
        fail("Backblaze device sw_version must match canonical App version")
    if payload.get("origin", {}).get("sw_version") != context["version"]:
        fail("Backblaze origin sw_version must match canonical App version")
