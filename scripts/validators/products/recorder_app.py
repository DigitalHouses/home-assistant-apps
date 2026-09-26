from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from validators.common import fail, require_files

EXPECTED_PRODUCT_ID = "digitalhouses_recorder_app"
EXPECTED_ENTITY_PREFIX = "dh_recorder_app"
EXPECTED_BASE_TOPIC = (
    "DigitalHouses/Global/digitalhouses_recorder_app"
)
EXPECTED_DEVICE_ID = "digitalhouses_recorder_app"
EXPECTED_IMAGE = (
    "ghcr.io/digitalhouses/digitalhouses_recorder_app"
)

LEGACY_BASE_TOPIC = "DigitalHouses/Global/db_monitoring"
LEGACY_DEVICE_ID = "digitalhouses_db_monitoring"


def _import_module(
    path: Path,
    module_name: str,
):
    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
    )
    if spec is None or spec.loader is None:
        fail(f"Unable to import {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _import_discovery(app: Path):
    return _import_module(
        app / "rootfs/app/discovery.py",
        "digitalhouses_recorder_app_discovery_validation",
    )


def _import_telemetry(app: Path):
    return _import_module(
        app / "rootfs/app/telemetry.py",
        "digitalhouses_recorder_app_telemetry_validation",
    )


def _assert_canonical_entity_ids(
    components: dict[str, Any],
) -> None:
    for key, component in components.items():
        if not isinstance(component, dict):
            fail(
                "Recorder App discovery component "
                f"{key} must be a mapping"
            )
        entity_id = component.get("default_entity_id")
        if not isinstance(entity_id, str):
            fail(
                "Recorder App discovery component "
                f"{key} is missing default_entity_id"
            )
        _, separator, object_id = entity_id.partition(".")
        if not separator or not object_id.startswith(
            f"{EXPECTED_ENTITY_PREFIX}_"
        ):
            fail(
                "Recorder App active discovery must use "
                f"{EXPECTED_ENTITY_PREFIX}_*: {entity_id!r}"
            )
        if "dh_db_" in entity_id:
            fail(
                "Recorder App canonical discovery contains "
                f"legacy entity ID {entity_id!r}"
            )


def validate_db_monitoring(
    root: Path,
    app: Path,
    context: dict[str, Any],
) -> None:
    config = context["config"]
    version = str(context["version"])

    require_files(
        root,
        [
            app / "rootfs/app/contracts.py",
            app / "rootfs/app/identity_migration.py",
            app / "rootfs/app/telemetry.py",
            app / "tests/test_contracts.py",
            app / "tests/test_identity_migration.py",
            app / "tests/test_telemetry.py",
        ],
    )

    if config.get("slug") != EXPECTED_PRODUCT_ID:
        fail(
            f"{app.name}: config slug must remain canonical "
            f"{EXPECTED_PRODUCT_ID!r}"
        )

    if config.get("image") != EXPECTED_IMAGE:
        fail(
            f"{app.name}: immutable production image must be "
            f"{EXPECTED_IMAGE!r}"
        )

    options = config.get("options") or {}
    schema = config.get("schema") or {}
    if options.get("telemetry_enabled") is not False:
        fail(
            f"{app.name}: telemetry_enabled must default to false"
        )
    if schema.get("telemetry_enabled") != "bool":
        fail(
            f"{app.name}: telemetry_enabled schema must be bool"
        )

    if "DH_SLUG_MIGRATION_MODE" in (
        config.get("environment") or {}
    ):
        fail(
            f"{app.name}: completed slug migration mode "
            "must be removed"
        )

    mappings = config.get("map") or []
    if any(
        isinstance(item, dict)
        and item.get("type") == "share"
        for item in mappings
    ):
        fail(
            f"{app.name}: temporary slug-migration share "
            "mapping must be removed"
        )

    if (
        app / "rootfs" / "app" / "slug_migration.py"
    ).exists():
        fail(
            f"{app.name}: completed slug migration runtime "
            "must be removed"
        )

    discovery = _import_discovery(app)

    if discovery.BASE_TOPIC != EXPECTED_BASE_TOPIC:
        fail(
            "Recorder App canonical MQTT base topic changed"
        )
    if discovery.DEVICE_ID != EXPECTED_DEVICE_ID:
        fail(
            "Recorder App canonical discovery device ID changed"
        )
    if discovery.ENTITY_PREFIX != EXPECTED_ENTITY_PREFIX:
        fail(
            "Recorder App canonical HA entity prefix changed"
        )
    if discovery.LEGACY_BASE_TOPIC != LEGACY_BASE_TOPIC:
        fail(
            "Recorder App bridge legacy MQTT base changed"
        )
    if discovery.LEGACY_DEVICE_ID != LEGACY_DEVICE_ID:
        fail(
            "Recorder App bridge legacy device ID changed"
        )
    if discovery.EVENT_SCHEMA_VERSION != 2:
        fail(
            "Recorder diagnostic event schema version must be 2"
        )

    payload = discovery.build_discovery_payload(
        app_version=version,
        include_storage=True,
    )
    components = payload.get("components") or {}
    _assert_canonical_entity_ids(components)

    if payload.get("device", {}).get(
        "identifiers"
    ) != [EXPECTED_DEVICE_ID]:
        fail(
            "Recorder App canonical discovery device "
            "identifier is invalid"
        )
    if payload.get("device", {}).get(
        "sw_version"
    ) != version:
        fail(
            "Recorder App device.sw_version must equal "
            "release version"
        )
    if payload.get("origin", {}).get(
        "sw_version"
    ) != version:
        fail(
            "Recorder App origin.sw_version must equal "
            "release version"
        )

    required_entities = {
        "app_version": (
            "sensor.dh_recorder_app_version"
        ),
        "app_started_at": (
            "sensor.dh_recorder_app_started_at"
        ),
        "database_type": (
            "sensor.dh_recorder_app_database_type"
        ),
        "db_start": (
            "sensor.dh_recorder_app_db_start"
        ),
        "db_connected": (
            "binary_sensor.dh_recorder_app_db_connected"
        ),
        "recorder_writing": (
            "binary_sensor.dh_recorder_app_recorder_writing"
        ),
        "db_refresh": (
            "button.dh_recorder_app_db_refresh"
        ),
        "db_disk_usage_threshold": (
            "number.dh_recorder_app_"
            "db_disk_usage_threshold"
        ),
        "diagnostic_event": (
            "event.dh_recorder_app_diagnostic"
        ),
        "delete_telemetry": (
            "button.dh_recorder_app_delete_telemetry"
        ),
    }
    for key, expected_entity_id in (
        required_entities.items()
    ):
        component = components.get(key)
        if not isinstance(component, dict):
            fail(
                "Recorder App missing discovery component "
                f"{key}"
            )
        if component.get(
            "default_entity_id"
        ) != expected_entity_id:
            fail(
                "Recorder App unexpected default_entity_id "
                f"for {key}: "
                f"{component.get('default_entity_id')!r}"
            )

    if components["app_version"].get(
        "entity_category"
    ) != "diagnostic":
        fail(
            "Recorder App Version must be diagnostic"
        )
    if components["app_started_at"].get(
        "entity_category"
    ) != "diagnostic":
        fail(
            "Recorder App Started at must be diagnostic"
        )
    if components["app_started_at"].get(
        "device_class"
    ) != "timestamp":
        fail(
            "Recorder App Started at must use timestamp "
            "device class"
        )

    canonical_unique_ids = [
        component.get("unique_id")
        for component in components.values()
    ]
    if len(canonical_unique_ids) != len(
        set(canonical_unique_ids)
    ):
        fail(
            "Recorder App canonical discovery contains "
            "duplicate unique IDs"
        )

    event_component = components["diagnostic_event"]
    expected_event_types = {
        "db_connection_lost",
        "db_connection_restored",
        "recorder_writing_stopped",
        "recorder_writing_restored",
        "storage_usage_high",
        "storage_usage_normal",
    }
    if set(
        event_component.get("event_types") or []
    ) != expected_event_types:
        fail(
            "Recorder diagnostic event types changed"
        )

    legacy_payload = (
        discovery.build_legacy_discovery_payload(
            app_version=version,
            include_storage=True,
        )
    )
    legacy_components = (
        legacy_payload.get("components") or {}
    )
    if legacy_payload.get("device", {}).get(
        "identifiers"
    ) != [LEGACY_DEVICE_ID]:
        fail(
            "Recorder App bridge must preserve legacy "
            "device identifier"
        )

    legacy_contract = {
        "db_start": (
            "digitalhouses_db_monitoring_db_start",
            "sensor.dh_db_start",
        ),
        "db_connected": (
            "digitalhouses_db_monitoring_db_connected",
            "binary_sensor.dh_db_connected",
        ),
        "recorder_writing": (
            "digitalhouses_db_monitoring_recorder_writing",
            "binary_sensor.dh_db_recorder_writing",
        ),
        "db_refresh": (
            "digitalhouses_db_monitoring_db_refresh",
            "button.dh_db_refresh",
        ),
        "db_disk_usage_threshold": (
            "digitalhouses_db_monitoring_"
            "db_disk_usage_threshold",
            "number.dh_db_disk_usage_threshold",
        ),
        "diagnostic_event": (
            "digitalhouses_db_monitoring_diagnostic_event",
            "event.dh_db_diagnostic",
        ),
    }
    for key, (
        expected_unique_id,
        expected_entity_id,
    ) in legacy_contract.items():
        component = legacy_components.get(key)
        if not isinstance(component, dict):
            fail(
                "Recorder App bridge missing legacy "
                f"component {key}"
            )
        if component.get(
            "unique_id"
        ) != expected_unique_id:
            fail(
                "Recorder App bridge changed legacy "
                f"unique_id for {key}"
            )
        if component.get(
            "default_entity_id"
        ) != expected_entity_id:
            fail(
                "Recorder App bridge changed legacy "
                f"entity ID for {key}"
            )

    for canonical_only in (
        "app_version",
        "app_started_at",
        "database_type",
        "delete_telemetry",
    ):
        if canonical_only in legacy_components:
            fail(
                "Recorder App bridge must not add canonical-"
                "only component to legacy device: "
                f"{canonical_only}"
            )

    telemetry = _import_telemetry(app)
    if telemetry.PRODUCT != EXPECTED_PRODUCT_ID:
        fail(
            "Recorder App telemetry PRODUCT must equal "
            "canonical product ID"
        )
    if str(telemetry.STATE_FILE) != (
        "/data/telemetry.json"
    ):
        fail(
            "Recorder App telemetry identity must persist "
            "in /data/telemetry.json"
        )
    if telemetry.HTTP_TIMEOUT_SECONDS != 5.0:
        fail(
            "Recorder App telemetry HTTP timeout must be 5s"
        )

    run_text = (
        app / "rootfs" / "run.sh"
    ).read_text(encoding="utf-8")
    if "${APP_VERSION:-unknown}" in run_text:
        fail(
            "Recorder App run.sh must not synthesize "
            "unknown release version"
        )
    if "APP_VERSION is required." not in run_text:
        fail(
            "Recorder App run.sh must fail visibly when "
            "APP_VERSION is missing"
        )

    app_text = (
        app / "rootfs" / "app" / "app.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "0.1.14-local",
        "APP_VERSION', '",
        'APP_VERSION", "',
    ):
        if forbidden in app_text:
            fail(
                "Recorder App runtime contains synthetic "
                f"version fallback {forbidden!r}"
            )

    for public_path in (
        app / "README.md",
        app / "DOCS.md",
    ):
        text = public_path.read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "script.write2log",
            "192.168.",
        ):
            if forbidden in text:
                fail(
                    f"{public_path.relative_to(root)} "
                    "contains private/site-specific "
                    f"dependency {forbidden!r}"
                )
