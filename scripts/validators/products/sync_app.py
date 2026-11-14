"""Product-specific contract for the DigitalHouses Sync App preview."""
from __future__ import annotations

from pathlib import Path

from validators.common import fail, require_files


def validate_sync_app(root: Path, app: Path, context: dict) -> None:
    require_files(root, [
        app / "docs/ARCHITECTURE.md",
        app / "docs/ADOPTION.md",
        app / "docs/STORAGE_MIGRATION.md",
        app / "rootfs/app/ha_bridge.py",
        app / "rootfs/app/migration_cli.py",
        app / "tests/test_ha_bridge.py",
        app / "rootfs/app/storage_migration.py",
        app / "tests/test_storage_migration.py",
        app / "rootfs/app/sync_engine.py",
        app / "rootfs/app/discovery_contract.py",
        app / "tests/test_discovery_contract.py",
        app / "docs/DH_SYNC_DISCOVERY_CONTRACT_V1.md",
        app / "rootfs/app/ha_core.py",
        app / "rootfs/app/sync_web.py",
        app / "tests/test_sync_engine.py",
        app / "tests/test_sync_web.py",
        app / "docs/FIRST_VERSION.md",
        app / "rootfs/app/adoption.py",
        app / "tests/test_adoption.py",
        app / "docs/PRODUCT_REQUIREMENTS.md",
        app / "docs/DEVELOPER_HANDOFF_RU.md",
        app / "docs/MQTT_INVENTORY.md",
        app / "rootfs/app/inventory.py",
        app / "rootfs/app/app.py",
        app / "tests/test_inventory.py",
        app / "icon.png",
        app / "logo.png",
    ])
    config = context["config"]
    if config.get("slug") != "digitalhouses_sync_app":
        fail("DH Sync: incorrect Supervisor slug")
    maps = config.get("map", [])
    if not any(isinstance(x, dict) and
               x.get("type") == "homeassistant_config" and
               x.get("read_only") is False for x in maps):
        fail("DH Sync v0.1 requires supervised HA configuration write mount")
    if not config.get("homeassistant_api"):
        fail("DH Sync requires the local Supervisor Core API")
    if not config.get("ingress") or config.get("ingress_port") != 8099:
        fail("DH Sync requires admin-only Ingress at port 8099")
    if config.get("panel_admin") is not True:
        fail("DH Sync Ingress must be admin-only")
    if config.get("options", {}).get("allow_changes") is not False:
        fail("DH Sync must default to read-only behavior")
