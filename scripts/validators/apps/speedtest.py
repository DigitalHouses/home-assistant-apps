from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from validators.common import fail, load_yaml, require_files

EXPECTED_TOPIC = "DigitalHouses/Global/speedtest"
EXPECTED_DEVICE_ID = "digitalhouses_global_speedtest"


def _import_discovery(app: Path):
    path = app / "rootfs/app/discovery.py"
    spec = importlib.util.spec_from_file_location(
        "digitalhouses_speedtest_discovery_validation",
        path,
    )
    if spec is None or spec.loader is None:
        fail("Unable to import Speedtest discovery.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_speedtest(root: Path, app: Path, context: dict[str, Any]) -> None:
    require_files(
        root,
        [
            app / "rootfs/app/app.py",
            app / "rootfs/app/core.py",
            app / "rootfs/app/discovery.py",
            app / "examples/packages/dh_app_speedtest_internet_global_package.yaml",
            app / "examples/packages/dh_app_internet_settings_passport_local_package.yaml",
            app / "examples/lovelace/dh_app_speedtest_dashboard.yaml",
        ],
    )

    version = context["version"]
    config = context["config"]

    if config.get("arch") != ["amd64"]:
        fail("Speedtest published architecture contract must remain ['amd64']")

    options = config.get("options") or {}
    schema = config.get("schema") or {}

    if options.get("periodic_test_interval_minutes") != 30:
        fail("Speedtest new-install periodic interval default must be 30 minutes")
    if options.get("recent_results_limit") != 20:
        fail("Speedtest recent_results_limit default must be 20")
    if "recent_results_limit" not in schema:
        fail("Speedtest recent_results_limit schema is missing")

    app_source = (app / "rootfs/app/app.py").read_text(encoding="utf-8")
    if f'MQTT_BASE_TOPIC = "{EXPECTED_TOPIC}"' not in app_source:
        fail("Speedtest MQTT base topic changed")
    if f'DEVICE_ID = "{EXPECTED_DEVICE_ID}"' not in app_source:
        fail("Speedtest device identifier changed")

    for expected in (
        'STATE_FILE = DATA_DIR / "state.json"',
        'THRESHOLDS_FILE = DATA_DIR / "thresholds.json"',
        'RECENT_RESULTS_FILE = DATA_DIR / "recent_results.json"',
        'SCHEDULE_FILE = DATA_DIR / "schedule.json"',
    ):
        if expected not in app_source:
            fail(f"Speedtest missing persistence contract: {expected}")

    discovery = _import_discovery(app)
    if discovery.DEVICE_ID != EXPECTED_DEVICE_ID:
        fail("Speedtest Discovery device identifier changed")

    topics = {
        "state": f"{EXPECTED_TOPIC}/state",
        "command": f"{EXPECTED_TOPIC}/command",
        "app_availability": f"{EXPECTED_TOPIC}/availability",
        "result_availability": f"{EXPECTED_TOPIC}/result_availability",
        "connectivity": f"{EXPECTED_TOPIC}/connectivity",
        "servers": f"{EXPECTED_TOPIC}/servers",
        "thresholds": f"{EXPECTED_TOPIC}/thresholds",
        "problems": f"{EXPECTED_TOPIC}/problems",
        "recent_results": f"{EXPECTED_TOPIC}/recent_results",
        "schedule": f"{EXPECTED_TOPIC}/schedule",
        "minimum_download_command": f"{EXPECTED_TOPIC}/thresholds/minimum_download/set",
        "minimum_upload_command": f"{EXPECTED_TOPIC}/thresholds/minimum_upload/set",
        "maximum_ping_command": f"{EXPECTED_TOPIC}/thresholds/maximum_ping/set",
        "periodic_interval_command": f"{EXPECTED_TOPIC}/schedule/periodic_interval/set",
    }

    payload = discovery.build_discovery_payload(
        app_version=version,
        expire_after_seconds=14400,
        topics=topics,
    )
    components = payload.get("components") or {}

    for key, (unique_id, entity_id) in discovery.LEGACY_COMPONENT_IDENTITIES.items():
        component = components.get(key)
        if not isinstance(component, dict):
            fail(f"Speedtest missing legacy discovery component {key}")
        if component.get("unique_id") != unique_id:
            fail(f"Speedtest legacy unique_id changed for {key}")
        if component.get("default_entity_id") != entity_id:
            fail(f"Speedtest legacy default_entity_id changed for {key}")

    expected_new = {
        "minimum_download": "number.internet_speed_minimum_download",
        "minimum_upload": "number.internet_speed_minimum_upload",
        "maximum_ping": "number.internet_speed_maximum_ping",
        "low_download": "binary_sensor.internet_speed_low_download",
        "low_upload": "binary_sensor.internet_speed_low_upload",
        "high_ping": "binary_sensor.internet_speed_high_ping",
        "performance_problem": "binary_sensor.internet_speed_performance_problem",
        "recent_results": "sensor.internet_speed_recent_results",
        "periodic_interval": "number.internet_speed_periodic_interval",
    }
    for key, entity_id in expected_new.items():
        component = components.get(key)
        if not isinstance(component, dict):
            fail(f"Speedtest missing discovery component {key}")
        if component.get("default_entity_id") != entity_id:
            fail(f"Speedtest unexpected default_entity_id for {key}")

    package = load_yaml(
        app / "examples/packages/dh_app_speedtest_internet_global_package.yaml",
        root,
    )
    if not isinstance(package, dict):
        fail("Speedtest Internet global package must be a YAML mapping")
    if "dh_app_speedtest_internet_global_package" not in package:
        fail("Speedtest Internet global package has unexpected top-level key")

    passport = load_yaml(
        app / "examples/packages/dh_app_internet_settings_passport_local_package.yaml",
        root,
    )
    if not isinstance(passport, dict):
        fail("Internet settings passport must be a YAML mapping")
    if "dh_app_internet_settings_passport_local_package" not in passport:
        fail("Internet settings passport has unexpected top-level key")

    dashboard = load_yaml(
        app / "examples/lovelace/dh_app_speedtest_dashboard.yaml",
        root,
    )
    if not isinstance(dashboard, dict):
        fail("Speedtest Lovelace dashboard must be a YAML mapping")

    if dashboard.get("type") == "sections":
        sections = dashboard.get("sections")
    elif isinstance(dashboard.get("views"), list):
        section_views = [
            view
            for view in dashboard["views"]
            if isinstance(view, dict) and view.get("type") == "sections"
        ]
        if not section_views:
            fail("Speedtest Lovelace dashboard has no Sections view")
        sections = section_views[0].get("sections")
    else:
        fail("Speedtest Lovelace dashboard must use Sections view")

    if not isinstance(sections, list) or not sections:
        fail("Speedtest Lovelace dashboard has no sections")
