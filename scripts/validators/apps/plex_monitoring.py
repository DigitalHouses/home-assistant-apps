from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from validators.common import fail, require_files

EXPECTED_TOPIC_PREFIX = "DigitalHouses/Global/plex_monitoring"
EXPECTED_INSTANCE_ID = "plex"
EXPECTED_DEVICE_ID = "digitalhouses_plex_monitoring_plex"

EXPECTED_ENTITY_IDS = {
    "activity": "sensor.dh_plex_activity",
    "current_item": "sensor.dh_plex_current_item",
    "server_running": "binary_sensor.dh_plex_server_running",
    "scanner_running": "binary_sensor.dh_plex_scanner_running",
    "credits_detection": "binary_sensor.dh_plex_credits_detection",
    "intro_detection": "binary_sensor.dh_plex_intro_detection",
    "thumbnail_generation": "binary_sensor.dh_plex_thumbnail_generation",
    "transcoder_running": "binary_sensor.dh_plex_transcoder_running",
    "cpu": "sensor.dh_plex_cpu",
    "cpu_avg": "sensor.dh_plex_cpu_avg",
    "cpu_max": "sensor.dh_plex_cpu_max",
    "scanner_cpu": "sensor.dh_plex_scanner_cpu",
    "scanner_cpu_avg": "sensor.dh_plex_scanner_cpu_avg",
    "scanner_cpu_max": "sensor.dh_plex_scanner_cpu_max",
    "transcoder_cpu": "sensor.dh_plex_transcoder_cpu",
    "transcoder_cpu_avg": "sensor.dh_plex_transcoder_cpu_avg",
    "transcoder_cpu_max": "sensor.dh_plex_transcoder_cpu_max",
    "scanner_actions": "sensor.dh_plex_scanner_actions",
    "process_count": "sensor.dh_plex_process_count",
    "collector_status": "sensor.dh_plex_collector_status",
    "last_refresh": "sensor.dh_plex_last_refresh",
    "build": "sensor.dh_plex_build",
    "refresh": "button.dh_plex_refresh",
}


def _load_package(app: Path):
    package_name = "_digitalhouses_plex_monitoring_validation"
    app_dir = app / "app"
    init_path = app_dir / "__init__.py"

    package_spec = importlib.util.spec_from_file_location(
        package_name,
        init_path,
        submodule_search_locations=[str(app_dir)],
    )
    if package_spec is None or package_spec.loader is None:
        fail("Unable to load Plex Monitoring app package")

    package = importlib.util.module_from_spec(package_spec)
    sys.modules[package_name] = package
    package_spec.loader.exec_module(package)

    def load_module(name: str):
        path = app_dir / f"{name}.py"
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.{name}",
            path,
        )
        if spec is None or spec.loader is None:
            fail(f"Unable to import Plex Monitoring {name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    try:
        config = load_module("config")
        models = load_module("models")
        discovery = load_module("discovery")
        return config, models, discovery
    finally:
        for name in list(sys.modules):
            if name == package_name or name.startswith(f"{package_name}."):
                sys.modules.pop(name, None)


def validate_plex_monitoring(
    root: Path,
    app: Path,
    context: dict[str, Any],
) -> None:
    require_files(
        root,
        [
            app / "requirements.txt",
            app / "app/config.py",
            app / "app/models.py",
            app / "app/discovery.py",
            app / "app/build_info.py",
            app / "examples/digitalhouses_plex_monitoring.conf.example",
            app / "systemd/digitalhouses_plex_monitoring.service",
        ],
    )

    if context.get("type") != "linux_agent":
        fail("Plex Monitoring must remain a linux_agent")

    config_module, models_module, discovery_module = _load_package(app)

    config = config_module.AppConfig(
        general=config_module.GeneralConfig(
            instance_id=EXPECTED_INSTANCE_ID,
            instance_name="DH Plex",
            poll_interval_seconds=10.0,
            cpu_window_seconds=60.0,
            log_level="info",
        ),
        telemetry=config_module.TelemetryConfig(
            cpu_change_threshold=5.0,
            high_load_threshold=80.0,
            high_load_publish_interval_seconds=60.0,
        ),
        mqtt=config_module.MqttConfig(
            host="mqtt.example",
            port=1883,
            username="",
            password="",
            topic_prefix=EXPECTED_TOPIC_PREFIX,
            discovery_prefix="homeassistant",
            keepalive_seconds=60,
        ),
    )
    build = models_module.BuildInfo(
        version=str(context["version"]),
        source="main",
        commit="0123456789abcdef0123456789abcdef01234567",
    )

    topics = discovery_module.build_topics(config)
    expected_base = f"{EXPECTED_TOPIC_PREFIX}/{EXPECTED_INSTANCE_ID}"
    expected_topics = {
        "base": expected_base,
        "state": f"{expected_base}/state",
        "app_availability": f"{expected_base}/availability",
        "collector_availability": f"{expected_base}/collector_availability",
        "refresh": f"{expected_base}/refresh",
        "discovery": (
            "homeassistant/device/"
            f"{EXPECTED_DEVICE_ID}/config"
        ),
        "ha_status": "homeassistant/status",
        "device_id": EXPECTED_DEVICE_ID,
    }
    for field, expected in expected_topics.items():
        if getattr(topics, field) != expected:
            fail(f"Plex Monitoring topic contract changed for {field}")

    payload = discovery_module.build_discovery_payload(config, build)
    device = payload.get("device") or {}
    if device.get("identifiers") != [EXPECTED_DEVICE_ID]:
        fail("Plex Monitoring Discovery device identifier changed")

    components = payload.get("components") or {}
    if set(components) != set(EXPECTED_ENTITY_IDS):
        missing = sorted(set(EXPECTED_ENTITY_IDS) - set(components))
        extra = sorted(set(components) - set(EXPECTED_ENTITY_IDS))
        fail(
            "Plex Monitoring discovery component set changed: "
            f"missing={missing}, extra={extra}"
        )

    for key, expected_entity_id in EXPECTED_ENTITY_IDS.items():
        component = components.get(key)
        if not isinstance(component, dict):
            fail(f"Plex Monitoring missing discovery component {key}")
        if component.get("default_entity_id") != expected_entity_id:
            fail(f"Plex Monitoring default_entity_id changed for {key}")

    example = (
        app / "examples/digitalhouses_plex_monitoring.conf.example"
    ).read_text(encoding="utf-8")
    for expected in (
        "instance_id = plex",
        "poll_interval_seconds = 10",
        "cpu_window_seconds = 60",
        "cpu_change_threshold = 5",
        "high_load_threshold = 80",
        "high_load_publish_interval_seconds = 60",
        "topic_prefix = DigitalHouses/Global/plex_monitoring",
    ):
        if expected not in example:
            fail(f"Plex Monitoring example config lost contract: {expected}")

    service = (
        app / "systemd/digitalhouses_plex_monitoring.service"
    ).read_text(encoding="utf-8")
    for expected in (
        "User=digitalhouses_plex_monitoring",
        "Group=digitalhouses_plex_monitoring",
        (
            "ExecStart=/opt/digitalhouses/digitalhouses_plex_monitoring/"
            ".venv/bin/python -m app.app --config "
            "/etc/digitalhouses_plex_monitoring/"
            "digitalhouses_plex_monitoring.conf"
        ),
        "ReadWritePaths=/var/lib/digitalhouses_plex_monitoring",
    ):
        if expected not in service:
            fail(f"Plex Monitoring systemd contract changed: {expected}")

    installer = (app / "install.sh").read_text(encoding="utf-8")
    for expected in (
        'APP_NAME="digitalhouses_plex_monitoring"',
        'APP_DIR="/opt/digitalhouses/${APP_NAME}"',
        'CONFIG_DIR="/etc/${APP_NAME}"',
        'STATE_DIR="/var/lib/${APP_NAME}"',
        'if [[ ! -f "${CONFIG_FILE}" ]]; then',
        'SOURCE_SHA="$(git -C "${tmp_dir}/repo" rev-parse HEAD)"',
        '} >"${APP_DIR}/BUILD_INFO"',
    ):
        if expected not in installer:
            fail(f"Plex Monitoring installer contract changed: {expected}")
