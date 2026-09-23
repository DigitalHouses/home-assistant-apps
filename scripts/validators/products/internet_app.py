from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from validators.common import fail, load_yaml, require_files


def validate_internet(root: Path, app: Path, context: dict[str, Any]) -> None:
    config = context["config"]
    options = config.get("options")
    schema = config.get("schema")
    if not isinstance(options, dict) or not isinstance(schema, dict):
        fail(f"{app.name}: options and schema must be mappings")

    if "router_ip" not in options:
        fail(f"{app.name}: router_ip must be an App option")
    if "speedtest" not in options:
        fail(f"{app.name}: speedtest must be an App option")
    if "traffic" not in options:
        fail(f"{app.name}: traffic must be an App option")

    traffic = options.get("traffic")
    if not isinstance(traffic, dict):
        fail(f"{app.name}: traffic options must be a mapping")
    expected_traffic_keys = {
        "traffic_download_total",
        "traffic_upload_total",
        "router_wan_status",
        "router_download_rate",
        "router_upload_rate",
    }
    if set(traffic) != expected_traffic_keys:
        fail(
            f"{app.name}: traffic binding contract must contain exactly "
            f"{sorted(expected_traffic_keys)!r}"
        )

    recovery = options.get("recovery")
    if not isinstance(recovery, dict):
        fail(f"{app.name}: recovery options must be a mapping")
    if recovery.get("mode") != "smart":
        fail(f"{app.name}: default recovery mode must be smart")

    for name in ("ont", "router"):
        target = recovery.get(name)
        if not isinstance(target, dict):
            fail(f"{app.name}: recovery.{name} must be a mapping")
        if target.get("action") not in {"button", "switch"}:
            fail(
                f"{app.name}: recovery.{name}.action must be button or switch"
            )

    discovery_path = app / "rootfs" / "app" / "discovery.py"
    discovery = discovery_path.read_text(encoding="utf-8")
    required = (
        'DEVICE_ID = "dh_internet_app"',
        'ENTITY_PREFIX = "dh_internet_app"',
        'MQTT_BASE_TOPIC = "DigitalHouses/Global/dh_internet_app"',
        '"name": "Version"',
        '"name": "Started at"',
        'EVENT_SCHEMA_VERSION = 2',
    )
    for value in required:
        if value not in discovery:
            fail(f"{app.name}: discovery contract is missing {value!r}")

    recovery_source = (app / "rootfs" / "app" / "recovery.py").read_text(
        encoding="utf-8"
    )
    if '"script"' in recovery_source or "'script'" in recovery_source:
        fail(f"{app.name}: script recovery action is forbidden")

    validate_presentation_examples(root, app, discovery)


def validate_presentation_examples(
    root: Path,
    app: Path,
    discovery: str,
) -> None:
    global_path = (
        app / "examples" / "packages" / "dh_internet_app_global_package.yaml"
    )
    notification_path = (
        app / "examples" / "packages" / "dh_internet_app_notification_package.yaml"
    )
    notification_ru_path = (
        app
        / "examples"
        / "packages"
        / "locales"
        / "dh_internet_app_notification_package_ru.yaml"
    )
    dashboard_path = (
        app / "examples" / "lovelace" / "dh_internet_app_dashboard.yaml"
    )
    require_files(
        root,
        [global_path, notification_path, notification_ru_path, dashboard_path],
    )

    global_package = load_yaml(global_path, root)
    notification = load_yaml(notification_path, root)
    notification_ru = load_yaml(notification_ru_path, root)
    dashboard = load_yaml(dashboard_path, root)

    if (
        not isinstance(global_package, dict)
        or "dh_internet_app_global_package" not in global_package
    ):
        fail(f"{app.name}: invalid global presentation package")
    if (
        not isinstance(notification, dict)
        or "dh_internet_app_notification_package" not in notification
    ):
        fail(f"{app.name}: invalid notification package")
    if (
        not isinstance(notification_ru, dict)
        or "dh_internet_app_notification_package_ru" not in notification_ru
    ):
        fail(f"{app.name}: invalid Russian notification package")
    if not isinstance(dashboard, dict) or dashboard.get("path") != "internet":
        fail(f"{app.name}: invalid reference dashboard")

    global_text = global_path.read_text(encoding="utf-8")
    notification_text = notification_path.read_text(encoding="utf-8")
    notification_ru_text = notification_ru_path.read_text(encoding="utf-8")
    dashboard_text = dashboard_path.read_text(encoding="utf-8")

    if "automation:" in global_text:
        fail(f"{app.name}: global package must remain Recorder-only")
    for text in (notification_text, notification_ru_text):
        if "event.dh_internet_app_event" not in text:
            fail(f"{app.name}: notification package must consume canonical Event")
        if "dh_internet_app_notification" not in text:
            fail(f"{app.name}: notification package must emit neutral event")
        for private_dependency in ("script.write2log", "notify.mobile_app", "telegram_bot."):
            if private_dependency in text:
                fail(
                    f"{app.name}: notification package contains private dependency "
                    f"{private_dependency!r}"
                )

    if "dh_internet_app_" not in dashboard_text:
        fail(f"{app.name}: dashboard must use canonical entities")

    discovered = {
        item.replace("{ENTITY_PREFIX}", "dh_internet_app")
        for item in re.findall(
            r'"default_entity_id":\s*f?"([^"]+)"',
            discovery,
        )
    }
    dashboard_entities = set(
        re.findall(
            r"\b(?:sensor|binary_sensor|button|number|event)\."
            r"dh_internet_app_[a-z0-9_]+",
            dashboard_text,
        )
    )
    missing = sorted(dashboard_entities - discovered)
    if missing:
        fail(
            f"{app.name}: dashboard references undiscovered entities: "
            + ", ".join(missing)
        )
