"""Product-specific HAOS and Recorder-safety validator for Zigbee Monitor."""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from validators.common import fail, load_yaml, require_files


def _translate(root: Path, app: Path, config: dict[str, Any]) -> None:
    schema = config.get("schema", {})
    for language in ("ru", "en"):
        payload = load_yaml(app / "translations" / f"{language}.yaml", root)
        cfg = payload.get("configuration") if isinstance(payload, dict) else None
        if not isinstance(cfg, dict):
            fail(f"{app.name}: {language} translations are invalid")
        for key in schema:
            item = cfg.get(key)
            if not isinstance(item, dict) or not item.get("name") or not item.get("description"):
                fail(f"{app.name}: missing {language} translation for {key}")
        for key in ("network_id", "name", "base_topic"):
            if key not in cfg["zigbee2mqtt"].get("fields", {}):
                fail(f"{app.name}: missing {language} zigbee2mqtt.{key} label")


def _png(path: Path, *, expected: tuple[int, int]) -> None:
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or len(raw) < 24:
        fail(f"{path}: expected PNG")
    if struct.unpack(">II", raw[16:24]) != expected:
        fail(f"{path}: invalid geometry, expected {expected}")


def validate_zigbee_monitor(root: Path, app: Path, context: dict[str, Any]) -> None:
    config = context["config"]
    options, schema = config.get("options"), config.get("schema")
    if not isinstance(options, dict) or not isinstance(schema, dict):
        fail(f"{app.name}: configuration options/schema required")
    if config.get("stage") != "experimental":
        fail(f"{app.name}: initial release must be experimental")
    if config.get("image") != "ghcr.io/digitalhouses/digitalhouses_zigbee_monitor_app":
        fail(f"{app.name}: image must use canonical GHCR identity")
    if config.get("hassio_role") != "default":
        fail(f"{app.name}: excess Supervisor privileges")
    if config.get("services") != ["mqtt:need"]:
        fail(f"{app.name}: Supervisor MQTT service required")
    if config.get("backup") != "cold":
        fail(f"{app.name}: SQLite must use cold App backups")
    if options.get("zigbee2mqtt") != []:
        fail(f"{app.name}: Zigbee2MQTT network list must not hardcode a site")
    if schema.get("zigbee2mqtt") != [{
        "network_id": "str", "name": "str", "base_topic": "str"
    }]:
        fail(f"{app.name}: network schema must declare stable ID, name and base topic")
    if options.get("telemetry_enabled") is not False or schema.get("telemetry_enabled") != "bool":
        fail(f"{app.name}: explicit telemetry consent must default to false")

    required = [
        "icon.png", "logo.png", "rootfs/app/app.py", "rootfs/run.sh",
        "rootfs/app/zigbee_monitor/core.py",
        "rootfs/app/zigbee_monitor/discovery.py",
        "rootfs/app/zigbee_monitor/service.py",
        "rootfs/app/zigbee_monitor/storage.py",
        "rootfs/app/zigbee_monitor/telemetry.py",
        "examples/packages/dh_zigbee_monitor_app_global_package.yaml",
        "examples/lovelace/dh_zigbee_monitor_app_dashboard.yaml",
        "tests/test_haos_contract.py",
    ]
    require_files(root, [app / p for p in required])
    _png(app / "icon.png", expected=(128, 128))
    _png(app / "logo.png", expected=(250, 100))
    _translate(root, app, config)

    app_code = (app / "rootfs/app/app.py").read_text(encoding="utf-8")
    service_code = (app / "rootfs/app/zigbee_monitor/service.py").read_text(encoding="utf-8")
    telemetry_code = (app / "rootfs/app/zigbee_monitor/telemetry.py").read_text(encoding="utf-8")
    if app_code.index('if options.get("telemetry_enabled") is not True:') > app_code.index("self.store = ActivityStore"):
        fail(f"{app.name}: consent must precede monitoring state")
    for field in ("schema", "telemetry_policy_version", "installation_id", "product", "version"):
        if f'"{field}"' not in telemetry_code:
            fail(f"{app.name}: missing telemetry field {field}")
    if 'TELEMETRY_POLICY_VERSION = 2' not in telemetry_code:
        fail(f"{app.name}: telemetry policy v2 required")
    if "self._state[\"installation_token\"] = secrets.token_hex(32)" not in telemetry_code:
        fail(f"{app.name}: deletion must rotate the installation token")
    if "self.monitor.reset_sources()" not in service_code:
        fail(f"{app.name}: reconnect must invalidate source observations")
    if "self.monitor.acknowledge_counts(snapshot)" not in service_code:
        fail(f"{app.name}: persisted activity must be acknowledged only after SQLite commit")

    discovery_code = (app / "rootfs/app/zigbee_monitor/discovery.py").read_text(encoding="utf-8")
    if "json_attributes_topic" not in discovery_code:
        fail(f"{app.name}: UI details must use a separate JSON topic")
    if "for key, (name, unit) in HISTORY.items():" not in discovery_code:
        fail(f"{app.name}: scalar history metrics contract missing")
    if "for key in DETAILS:" not in discovery_code:
        fail(f"{app.name}: details contract missing")
    pkg = load_yaml(
        app / "examples/packages/dh_zigbee_monitor_app_global_package.yaml", root,
    )
    recorder = pkg["dh_zigbee_monitor_app_global_package"]["recorder"]
    if not recorder.get("include", {}).get("entities"):
        fail(f"{app.name}: Recorder scalar allowlist required")
    if "sensor.dh_zigbee_monitor_app_*_details" not in recorder.get("exclude", {}).get("entity_globs", []):
        fail(f"{app.name}: Recorder detailed attributes must be excluded")
