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
    try:
        shutdown_timeout = int(config.get("timeout") or 0)
    except (TypeError, ValueError):
        shutdown_timeout = 0
    if shutdown_timeout < 35:
        fail(
            f"{app.name}: timeout must allow guarded switch power restore "
            "(minimum 35 seconds)"
        )
    if "speedtest" not in options:
        fail(f"{app.name}: speedtest must be an App option")
    if "traffic" not in options:
        fail(f"{app.name}: traffic must be an App option")
    if options.get("telemetry_enabled") is not False:
        fail(f"{app.name}: telemetry_enabled must exist and default to false")
    if schema.get("telemetry_enabled") != "bool":
        fail(f"{app.name}: telemetry_enabled schema must be bool")

    if config.get("slug") != "digitalhouses_internet_app":
        fail(
            f"{app.name}: config slug must remain canonical "
            "'digitalhouses_internet_app'"
        )

    if "DH_SLUG_MIGRATION_MODE" in (config.get("environment") or {}):
        fail(f"{app.name}: completed slug migration mode must be removed")

    mappings = config.get("map") or []
    if any(
        isinstance(item, dict) and item.get("type") == "share"
        for item in mappings
    ):
        fail(
            f"{app.name}: temporary migration share mapping must be removed"
        )

    migration_path = app / "rootfs" / "app" / "slug_migration.py"
    if migration_path.exists():
        fail(f"{app.name}: completed slug migration runtime must be removed")

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

    telemetry_path = app / "rootfs" / "app" / "telemetry.py"
    require_files(root, [telemetry_path])
    telemetry_source = telemetry_path.read_text(encoding="utf-8")
    for value in (
        'PRODUCT = "digitalhouses_internet_app"',
        'STATE_FILE = Path("/data/telemetry.json")',
        'BASE_URL = "https://telemetry.digitalhouses.vip"',
        '"telemetry_policy_version": TELEMETRY_POLICY_VERSION',
        '"installation_id": self.installation_id',
        '"product": PRODUCT',
        '"version": self.version',
    ):
        if value not in telemetry_source:
            fail(f"{app.name}: telemetry contract is missing {value!r}")

    validate_presentation_examples(root, app, discovery)
    validate_config_translations(root, app, schema)


def validate_config_translations(
    root: Path,
    app: Path,
    schema: dict[str, Any],
) -> None:
    paths = [
        app / "translations" / "en.yaml",
        app / "translations" / "ru.yaml",
    ]
    require_files(root, paths)

    def validate_level(
        schema_level: dict[str, Any],
        translations_level: dict[str, Any],
        *,
        locale: str,
        prefix: str = "",
    ) -> None:
        for key, value in schema_level.items():
            option_path = f"{prefix}.{key}" if prefix else key
            entry = translations_level.get(key)
            if not isinstance(entry, dict):
                fail(
                    f"{app.name}: {locale} translation missing "
                    f"{option_path!r}"
                )
            if not str(entry.get("name") or "").strip():
                fail(
                    f"{app.name}: {locale} translation {option_path!r} "
                    "must have a name"
                )
            if not str(entry.get("description") or "").strip():
                fail(
                    f"{app.name}: {locale} translation {option_path!r} "
                    "must have a description"
                )
            if isinstance(value, dict):
                fields = entry.get("fields")
                if not isinstance(fields, dict):
                    fail(
                        f"{app.name}: {locale} translation {option_path!r} "
                        "must use nested fields"
                    )
                validate_level(
                    value,
                    fields,
                    locale=locale,
                    prefix=option_path,
                )

    for path in paths:
        payload = load_yaml(path, root)
        configuration = (
            payload.get("configuration")
            if isinstance(payload, dict)
            else None
        )
        if not isinstance(configuration, dict):
            fail(
                f"{app.name}: invalid configuration translations in "
                f"{path.name}"
            )
        validate_level(
            schema,
            configuration,
            locale=path.stem,
        )


def validate_presentation_examples(
    root: Path,
    app: Path,
    discovery: str,
) -> None:
    global_path = (
        app / "examples" / "packages" / "dh_internet_app_global_package.yaml"
    )
    notification_path = (
        app / "examples" / "packages" / "dh_internet_app_notification_local_package.yaml"
    )
    notification_ru_path = (
        app
        / "examples"
        / "packages"
        / "locales"
        / "ru"
        / "dh_internet_app_notification_local_package.yaml"
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
        or "dh_internet_app_notification_local_package" not in notification
    ):
        fail(f"{app.name}: invalid notification package")
    if (
        not isinstance(notification_ru, dict)
        or "dh_internet_app_notification_local_package" not in notification_ru
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
        for required_marker in (
            "event.dh_internet_app_event",
            "- id: dh_internet_app_notifications",
            "trigger: event.received",
            "condition: trigger",
            "trigger.to_state.attributes",
        ):
            if required_marker not in text:
                fail(
                    f"{app.name}: notification package is missing "
                    f"{required_marker!r}"
                )
        for forbidden_marker in (
            "event: dh_internet_app_notification",
            "notification_schema_version",
            "kind: contract_error",
            "failure_class:",
            "machine_schema_version",
        ):
            if forbidden_marker in text:
                fail(
                    f"{app.name}: notification package must use direct delivery; "
                    f"found legacy marker {forbidden_marker!r}"
                )

    if "persistent_notification.create" not in notification_text:
        fail(f"{app.name}: English notification example must deliver directly")
    if "script.write2log" not in notification_ru_text:
        fail(f"{app.name}: Russian local notification package must deliver directly")

    if "dh_internet_app_" not in dashboard_text:
        fail(f"{app.name}: dashboard must use canonical entities")
    for required_filter in (
        'state: "unavailable"',
        'state: "unknown"',
        "condition: numeric_state",
    ):
        if required_filter not in dashboard_text:
            fail(
                f"{app.name}: dashboard optional-entity visibility contract "
                f"is missing {required_filter!r}"
            )

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
