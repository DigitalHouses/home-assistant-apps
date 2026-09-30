from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from validators.common import fail

EXPECTED_BASE_TOPIC = "DigitalHouses/Global/backblaze"
EXPECTED_DEVICE_ID = "digitalhouses_backblaze"
EXPECTED_REFRESH_TOPIC = f"{EXPECTED_BASE_TOPIC}/refresh"
EXPECTED_REFRESH_OPERATION_TOPIC = f"{EXPECTED_BASE_TOPIC}/refresh/operation"
EXPECTED_STORAGE_TREE_TOPIC = f"{EXPECTED_BASE_TOPIC}/storage_tree"
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
        "title: Total used by day",
        "type: statistics-graph",
        "chart_type: bar",
        "period: day",
        "days_to_show: 30",
        "- max",
        "sensor.dh_backblaze_storage_tree",
        "sensor.dh_backblaze_refresh_state",
        "sensor.dh_backblaze_last_refresh",
        "Backblaze B2",
        "Обновление…",
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
    if discovery.REFRESH_OPERATION_TOPIC != EXPECTED_REFRESH_OPERATION_TOPIC:
        fail("Backblaze refresh operation topic changed")
    if discovery.STORAGE_TREE_TOPIC != EXPECTED_STORAGE_TREE_TOPIC:
        fail("Backblaze storage tree topic changed")
    if discovery.TELEMETRY_DELETE_COMMAND_TOPIC != EXPECTED_TELEMETRY_DELETE_TOPIC:
        fail("Backblaze telemetry delete command topic changed")
    if discovery.DATA_AVAILABILITY_TOPIC != f"{EXPECTED_BASE_TOPIC}/data_availability":
        fail("Backblaze data availability topic changed")
    if discovery.API_OBSERVED_TOPIC != f"{EXPECTED_BASE_TOPIC}/api_observed":
        fail("Backblaze API observation availability topic changed")

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
        "storage_tree": "sensor.dh_backblaze_storage_tree",
        "last_refresh": "sensor.dh_backblaze_last_refresh",
        "refresh_state": "sensor.dh_backblaze_refresh_state",
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
        "{{ (value_json.stored_bytes / 1000000000) | round(1) }}"
    ):
        fail("Backblaze Total used must consume the pre-aggregated account total")

    primary_components = (
        "total_used",
        "bucket_count",
        "total_files",
        "total_versions",
        "storage_tree",
        "bucket_bucket-id_used",
        "bucket_bucket-id_files",
        "bucket_bucket-id_versions",
    )
    for key in primary_components:
        if components[key].get("entity_category") is not None:
            fail(f"Backblaze primary entity must not have entity_category: {key}")

    for key in ("total_used", "bucket_bucket-id_used"):
        if components[key].get("unit_of_measurement") != "GB":
            fail(f"Backblaze storage unit must be decimal GB: {key}")
        if components[key].get("device_class") is not None:
            fail(f"Backblaze storage sensor must not be unit-converted by HA: {key}")
        if components[key].get("suggested_display_precision") != 1:
            fail(f"Backblaze storage precision changed: {key}")
        if components[key].get("json_attributes_topic") is not None:
            fail(f"Backblaze storage entity must not expose bucket attributes: {key}")

    diagnostic_components = (
        "last_update",
        "last_refresh",
        "refresh_state",
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

    total_availability = {
        item.get("topic")
        for item in components["total_used"].get("availability", [])
        if isinstance(item, dict)
    }
    if total_availability != {
        discovery.APP_AVAILABILITY_TOPIC,
        discovery.DATA_AVAILABILITY_TOPIC,
    }:
        fail("Backblaze storage metrics must require App and B2 data availability")

    api_availability = {
        item.get("topic")
        for item in components["api_connected"].get("availability", [])
        if isinstance(item, dict)
    }
    if api_availability != {
        discovery.APP_AVAILABILITY_TOPIC,
        discovery.API_OBSERVED_TOPIC,
    }:
        fail("Backblaze API diagnostic must require a real API observation")

    support_url = payload.get("origin", {}).get("support_url")
    if not isinstance(support_url, str) or not support_url.endswith(
        "/digitalhouses_backblaze_app"
    ):
        fail("Backblaze Discovery support URL must use canonical repository directory")

    discovery_source = (app / "rootfs/app/discovery.py").read_text(
        encoding="utf-8"
    )
    for expected in (
        'DISCOVERY_SCHEMA_VERSION = 6',
        'DISCOVERY_SCHEMA_PATH = Path("/data/discovery_schema_version")',
        'DISCOVERY_MANIFEST_PATH = Path("/data/discovery_manifest.json")',
        "def dynamic_discovery_manifest(",
        "def removed_discovery_components(",
        "def discovery_cleanup_payload(",
        "def load_discovery_manifest(",
        "def save_discovery_manifest(",
    ):
        if expected not in discovery_source:
            fail(f"Backblaze discovery migration contract missing: {expected}")

    config = context["config"]
    if config.get("stage") != "stable":
        fail("Backblaze production App stage must be stable")
    if config.get("image") != "ghcr.io/digitalhouses/digitalhouses_backblaze_app":
        fail("Backblaze production App must use the canonical immutable GHCR image")

    options = context["config"].get("options") or {}
    if options.get("telemetry_enabled") is not False:
        fail("Backblaze telemetry must be disabled by default")

    app_source = (app / "rootfs/app/app.py").read_text(encoding="utf-8")
    for expected in (
        'APP_VERSION = os.environ.get("APP_VERSION")',
        'raise RuntimeError("APP_VERSION must be a valid semantic version")',
        "load_discovery_manifest()",
        "removed_discovery_components(",
        "save_discovery_manifest(current_manifest)",
        "confirm=True",
        'publish_text(DATA_AVAILABILITY_TOPIC, "offline", retain=True)',
        'publish_text(DATA_AVAILABILITY_TOPIC, "online", retain=True)',
        'publish_text(API_OBSERVED_TOPIC, "online", retain=True)',
        "self.publish_refresh_operation(self.refresh_operation)",
        "def refresh(self, *, manual: bool = False) -> bool:",
        "self.refresh(manual=manual_refresh)",
        "self.publish_storage_tree()",
        "self._commit_last_refresh(completed_at)",
    ):
        if expected not in app_source:
            fail(f"Backblaze runtime hardening contract missing: {expected}")
    for forbidden in (
        '"0.1.10-local"',
        '"0.1.11-local"',
        "APP_VERSION:-unknown",
    ):
        if forbidden in app_source:
            fail(f"Backblaze runtime must not synthesize Version: {forbidden}")

    run_script = (app / "rootfs/run.sh").read_text(encoding="utf-8")
    if 'APP_VERSION:-unknown' in run_script:
        fail("Backblaze run.sh must not synthesize unknown App version")
    if 'APP_VERSION is required.' not in run_script:
        fail("Backblaze run.sh must fail visibly when APP_VERSION is missing")

    b2_source = (app / "rootfs/app/backblaze.py").read_text(encoding="utf-8")
    for expected in (
        "def _required_string(",
        "def _required_non_negative_int(",
        "has unsupported action",
        "contentLength",
        "bucketName",
        "uploadTimestamp",
        "class FolderUsage:",
        "folder_totals",
    ):
        if expected not in b2_source:
            fail(f"Backblaze B2 contract-data validation missing: {expected}")
    for forbidden in (
        'item.get("contentLength") or 0',
        'bucket.get("bucketName") or bucket_id',
        'str(item.get("fileName") or "")',
    ):
        if forbidden in b2_source:
            fail(f"Backblaze B2 contract data must not use silent fallback: {forbidden}")

    operation = (app / "rootfs/app/operation_status.py").read_text(
        encoding="utf-8"
    )
    for expected in (
        'VALID_OPERATION_STATES = frozenset({"idle", "updating", "error"})',
        "def operation_payload(",
        '"started_at"',
        '"finished_at"',
        '"duration_seconds"',
        '"error"',
    ):
        if expected not in operation:
            fail(f"Backblaze refresh operation contract missing: {expected}")

    runtime_state = (app / "rootfs/app/runtime_state.py").read_text(
        encoding="utf-8"
    )
    for expected in (
        'RUNTIME_STATE_PATH = Path("/data/runtime_state.json")',
        "def load_last_refresh(",
        "def save_last_refresh(",
        "Runtime state is not valid JSON",
    ):
        if expected not in runtime_state:
            fail(f"Backblaze runtime-state contract missing: {expected}")

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
