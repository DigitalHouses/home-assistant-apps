from __future__ import annotations

from pathlib import Path
from typing import Any

from validators.common import fail


def validate_internet(root: Path, app: Path, context: dict[str, Any]) -> None:
    del root
    config = context["config"]
    options = config.get("options")
    schema = config.get("schema")
    if not isinstance(options, dict) or not isinstance(schema, dict):
        fail(f"{app.name}: options and schema must be mappings")

    if "router_ip" not in options:
        fail(f"{app.name}: router_ip must be an App option")

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

    discovery = (app / "rootfs" / "app" / "discovery.py").read_text(
        encoding="utf-8"
    )
    required = (
        'DEVICE_ID = "dh_internet_app"',
        'ENTITY_PREFIX = "dh_internet_app"',
        'MQTT_BASE_TOPIC = "DigitalHouses/Global/dh_internet_app"',
        '"name": "Version"',
        '"name": "Started at"',
    )
    for value in required:
        if value not in discovery:
            fail(f"{app.name}: discovery contract is missing {value!r}")

    recovery_source = (app / "rootfs" / "app" / "recovery.py").read_text(
        encoding="utf-8"
    )
    if '"script"' in recovery_source or "'script'" in recovery_source:
        fail(f"{app.name}: script recovery action is forbidden")
