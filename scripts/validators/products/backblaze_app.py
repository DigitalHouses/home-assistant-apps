from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from validators.common import fail

EXPECTED_BASE_TOPIC = "DigitalHouses/Global/backblaze"
EXPECTED_DEVICE_ID = "digitalhouses_backblaze"
EXPECTED_REFRESH_TOPIC = f"{EXPECTED_BASE_TOPIC}/refresh"
EXPECTED_TELEMETRY_DELETE_TOPIC = f"{EXPECTED_BASE_TOPIC}/telemetry/delete"


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
    del root
    required_examples = (
        app / "examples/packages/dh_app_backblaze_package.yaml",
        app / "examples/lovelace/dh_app_backblaze_dashboard.yaml",
    )
    for path in required_examples:
        if not path.is_file():
            fail(f"Backblaze example missing: {path.relative_to(app)}")

    package_text = required_examples[0].read_text(encoding="utf-8")
    for entity_id in (
        "sensor.dh_backblaze_storage_used",
        "sensor.dh_backblaze_files",
    ):
        if entity_id not in package_text:
            fail(f"Backblaze Recorder package missing: {entity_id}")
    if package_text.count("- sensor.") != 2:
        fail("Backblaze Recorder package must record exactly two sensors")

    dashboard_text = required_examples[1].read_text(encoding="utf-8")
    for expected in (
        "sensor.dh_backblaze_storage_used",
        "name: Total used by day",
        "type: statistics-graph",
        "chart_type: bar",
        "period: day",
        "days_to_show: 10",
        "- max",
    ):
        if expected not in dashboard_text:
            fail(f"Backblaze dashboard contract missing: {expected}")

    discovery = _import_discovery(app)

    if discovery.BASE_TOPIC != EXPECTED_BASE_TOPIC:
        fail("Backblaze MQTT base topic changed")
    if discovery.DEVICE_ID != EXPECTED_DEVICE_ID:
        fail("Backblaze discovery device identifier changed")
    if discovery.REFRESH_COMMAND_TOPIC != EXPECTED_REFRESH_TOPIC:
        fail("Backblaze refresh command topic changed")
    if discovery.TELEMETRY_DELETE_COMMAND_TOPIC != EXPECTED_TELEMETRY_DELETE_TOPIC:
        fail("Backblaze telemetry delete command topic changed")

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
        "telemetry_delete": "button.dh_backblaze_delete_telemetry",
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


    if components["total_files"].get("name") != "Total files":
        fail("Backblaze account file-count sensor must be named Total files")
    if components["total_files"].get("value_template") != "{{ value_json.current_files }}":
        fail("Backblaze Total files must consume the pre-aggregated account total")

    if components["total_used"].get("name") != "Total used":
        fail("Backblaze account storage sensor must be named Total used")
    if components["total_used"].get("value_template") != (
        "{{ (value_json.stored_bytes / 1073741824) | round(1) }}"
    ):
        fail("Backblaze Total used must consume the pre-aggregated account total")

    primary_components = (
        "total_used",
        "bucket_count",
        "total_files",
        "total_versions",
        "bucket_bucket-id_used",
        "bucket_bucket-id_files",
        "bucket_bucket-id_versions",
    )
    for key in primary_components:
        if components[key].get("entity_category") is not None:
            fail(f"Backblaze primary entity must not have entity_category: {key}")

    for key in ("total_used", "bucket_bucket-id_used"):
        if components[key].get("unit_of_measurement") != "GiB":
            fail(f"Backblaze storage unit changed: {key}")
        if components[key].get("suggested_display_precision") != 1:
            fail(f"Backblaze storage precision changed: {key}")
        if components[key].get("json_attributes_topic") is not None:
            fail(f"Backblaze storage entity must not expose bucket attributes: {key}")

    diagnostic_components = (
        "last_update",
        "api_connected",
        "app_version",
        "app_started_at",
    )
    for key in diagnostic_components:
        if components[key].get("entity_category") != "diagnostic":
            fail(f"Backblaze diagnostic entity category changed: {key}")

    for key in ("refresh", "telemetry_delete"):
        if components[key].get("entity_category") != "config":
            fail(f"Backblaze config entity category changed: {key}")

    started = components["app_started_at"]
    if started.get("device_class") != "timestamp":
        fail("Backblaze started-at diagnostic must use timestamp device class")
    if started.get("entity_category") != "diagnostic":
        fail("Backblaze started-at diagnostic must be diagnostic")


    discovery_source = (app / "rootfs/app/discovery.py").read_text(
        encoding="utf-8"
    )
    for expected in (
        'DISCOVERY_SCHEMA_VERSION = 2',
        'DISCOVERY_SCHEMA_PATH = Path("/data/discovery_schema_version")',
    ):
        if expected not in discovery_source:
            fail(f"Backblaze discovery migration contract missing: {expected}")

    options = context["config"].get("options") or {}
    if options.get("telemetry_enabled") is not False:
        fail("Backblaze telemetry must be disabled by default")

    telemetry = (app / "rootfs/app/telemetry.py").read_text(encoding="utf-8")
    required_telemetry_contract = (
        'PRODUCT = "digitalhouses_backblaze_app"',
        'path="/v1/heartbeat"',
        'method="DELETE"',
        'path="/v1/installation"',
        'STATE_FILE = Path("/data/telemetry_state.json")',
    )
    for expected in required_telemetry_contract:
        if expected not in telemetry:
            fail(f"Backblaze telemetry contract missing: {expected}")
