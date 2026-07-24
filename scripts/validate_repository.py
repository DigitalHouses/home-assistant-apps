#!/usr/bin/env python3
"""Repository-level release validation for DigitalHouses Home Assistant Apps."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "digitalhouses_speedtest"

REQUIRED_FILES = [
    ROOT / "repository.yaml",
    ROOT / "README.md",
    ROOT / "LICENSE",
    APP / "config.yaml",
    APP / "Dockerfile",
    APP / "README.md",
    APP / "DOCS.md",
    APP / "CHANGELOG.md",
    APP / "rootfs/run.sh",
    APP / "rootfs/app/app.py",
    APP / "rootfs/app/core.py",
    APP / "rootfs/app/discovery.py",
    APP / "tests/test_core.py",
    APP / "tests/test_discovery.py",
    APP / "tests/test_runtime.py",
    ROOT / "examples/packages/internet_speedtest_package.yaml",
    ROOT / "examples/lovelace/internet_speedtest_dashboard.yaml",
]

EXPECTED_VERSION = "1.1.1"
EXPECTED_TOPIC = "DigitalHouses/Global/speedtest"
EXPECTED_DEVICE_ID = "digitalhouses_global_speedtest"


def fail(message: str) -> None:
    raise SystemExit(f"VALIDATION FAILED: {message}")


def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"Unable to parse {path.relative_to(ROOT)}: {exc}")


def import_discovery():
    path = APP / "rootfs/app/discovery.py"
    spec = importlib.util.spec_from_file_location("speedtest_discovery", path)
    if spec is None or spec.loader is None:
        fail("Unable to import discovery.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    missing = [path for path in REQUIRED_FILES if not path.is_file()]
    if missing:
        fail(
            "Missing required files: "
            + ", ".join(str(path.relative_to(ROOT)) for path in missing)
        )

    config = load_yaml(APP / "config.yaml")
    if not isinstance(config, dict):
        fail("digitalhouses_speedtest/config.yaml must be a mapping")

    if str(config.get("version")) != EXPECTED_VERSION:
        fail(
            f"config version must be {EXPECTED_VERSION}, "
            f"got {config.get('version')!r}"
        )
    if config.get("slug") != "digitalhouses_speedtest":
        fail("Unexpected App slug")
    if config.get("stage") != "stable":
        fail("App stage must remain stable")
    if config.get("arch") != ["amd64"]:
        fail("Published architecture contract must remain ['amd64']")

    options = config.get("options") or {}
    schema = config.get("schema") or {}
    if options.get("periodic_test_interval_minutes") != 30:
        fail("New-install periodic interval default must be 30 minutes")
    if options.get("recent_results_limit") != 20:
        fail("recent_results_limit default must be 20")
    if "recent_results_limit" not in schema:
        fail("recent_results_limit schema is missing")

    app_source = (APP / "rootfs/app/app.py").read_text(encoding="utf-8")
    if f'MQTT_BASE_TOPIC = "{EXPECTED_TOPIC}"' not in app_source:
        fail("MQTT base topic changed")
    if f'DEVICE_ID = "{EXPECTED_DEVICE_ID}"' not in app_source:
        fail("Device identifier changed")
    for expected in (
        'STATE_FILE = DATA_DIR / "state.json"',
        'THRESHOLDS_FILE = DATA_DIR / "thresholds.json"',
        'RECENT_RESULTS_FILE = DATA_DIR / "recent_results.json"',
        'SCHEDULE_FILE = DATA_DIR / "schedule.json"',
    ):
        if expected not in app_source:
            fail(f"Missing persistence contract: {expected}")

    discovery = import_discovery()
    if discovery.DEVICE_ID != EXPECTED_DEVICE_ID:
        fail("Discovery device identifier changed")

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
        "minimum_download_command": (
            f"{EXPECTED_TOPIC}/thresholds/minimum_download/set"
        ),
        "minimum_upload_command": (
            f"{EXPECTED_TOPIC}/thresholds/minimum_upload/set"
        ),
        "maximum_ping_command": (
            f"{EXPECTED_TOPIC}/thresholds/maximum_ping/set"
        ),
        "periodic_interval_command": (
            f"{EXPECTED_TOPIC}/schedule/periodic_interval/set"
        ),
    }
    payload = discovery.build_discovery_payload(
        app_version=EXPECTED_VERSION,
        expire_after_seconds=14400,
        topics=topics,
    )
    components = payload.get("components") or {}

    for key, (unique_id, entity_id) in discovery.LEGACY_COMPONENT_IDENTITIES.items():
        component = components.get(key)
        if not isinstance(component, dict):
            fail(f"Missing legacy discovery component {key}")
        if component.get("unique_id") != unique_id:
            fail(f"Legacy unique_id changed for {key}")
        if component.get("default_entity_id") != entity_id:
            fail(f"Legacy default_entity_id changed for {key}")

    expected_new = {
        "minimum_download": "number.internet_speed_minimum_download",
        "minimum_upload": "number.internet_speed_minimum_upload",
        "maximum_ping": "number.internet_speed_maximum_ping",
        "low_download": "binary_sensor.internet_speed_low_download",
        "low_upload": "binary_sensor.internet_speed_low_upload",
        "high_ping": "binary_sensor.internet_speed_high_ping",
        "performance_problem": (
            "binary_sensor.internet_speed_performance_problem"
        ),
        "recent_results": "sensor.internet_speed_recent_results",
        "periodic_interval": "number.internet_speed_periodic_interval",
    }
    for key, entity_id in expected_new.items():
        component = components.get(key)
        if not isinstance(component, dict):
            fail(f"Missing new discovery component {key}")
        if component.get("default_entity_id") != entity_id:
            fail(f"Unexpected default_entity_id for {key}")

    recorder_data = load_yaml(
        ROOT / "examples/packages/internet_speedtest_package.yaml"
    )
    recorder_entities = (
        ((recorder_data or {}).get("recorder") or {})
        .get("include", {})
        .get("entities", [])
    )
    if "sensor.internet_speed_recent_results" in recorder_entities:
        fail("Recent results must remain excluded from Recorder")
    for entity_id in (
        "number.internet_speed_minimum_download",
        "number.internet_speed_minimum_upload",
        "number.internet_speed_maximum_ping",
        "number.internet_speed_periodic_interval",
        "binary_sensor.internet_speed_low_download",
        "binary_sensor.internet_speed_low_upload",
        "binary_sensor.internet_speed_high_ping",
        "binary_sensor.internet_speed_performance_problem",
    ):
        if entity_id not in recorder_entities:
            fail(f"Recorder package is missing {entity_id}")

    dashboard = load_yaml(
        ROOT / "examples/lovelace/internet_speedtest_dashboard.yaml"
    )
    if not isinstance(dashboard, dict) or not dashboard.get("views"):
        fail("Lovelace dashboard has no views")

    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
    if "## 1.1.1" not in changelog:
        fail("CHANGELOG has no 1.1.1 section")

    print("Repository validation passed")
    print(f"Version: {EXPECTED_VERSION}")
    print(f"Discovery components: {len(components)}")
    print(
        "Legacy identities preserved: "
        f"{len(discovery.LEGACY_COMPONENT_IDENTITIES)}"
    )


if __name__ == "__main__":
    main()
