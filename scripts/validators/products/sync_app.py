"""Product-specific contract for DigitalHouses automatic YAML synchronization."""
from __future__ import annotations

from pathlib import Path

from validators.common import fail, require_files


def validate_sync_app(root: Path, app: Path, context: dict) -> None:
    require_files(root, [
        Path("docs/standards/DH_SYNC_DEVELOPER_STANDARD.md"),
        app / "docs/ARCHITECTURE.md",
        app / "docs/ADOPTION.md",
        app / "docs/STORAGE_MIGRATION.md",
        app / "rootfs/app/ha_bridge.py",
        app / "rootfs/app/migration_cli.py",
        app / "tests/test_ha_bridge.py",
        app / "rootfs/app/storage_migration.py",
        app / "tests/test_storage_migration.py",
        app / "rootfs/app/sync_engine.py",
        app / "rootfs/app/catalog_web.py",
        app / "rootfs/app/resource_preview.py",
        app / "rootfs/app/git_source.py",
        app / "rootfs/app/auto_sync.py",
        app / "rootfs/app/dashboard_runtime.py",
        app / "rootfs/app/panel_config.py",
        app / "dashboards/dh-system.yaml",
        app / "tests/test_auto_sync.py",
        app / "tests/test_dashboard_runtime.py",
        app / "tests/test_git_source.py",
        app / "rootfs/app/local_audit.py",
        app / "rootfs/app/apply_service.py",
        app / "tests/test_apply_service.py",
        app / "tests/test_local_audit.py",
        app / "tests/test_resource_preview.py",
        app / "tests/test_catalog_web.py",
        app / "rootfs/app/discovery_contract.py",
        app / "tests/test_discovery_contract.py",
        app / "rootfs/app/ha_core.py",
        app / "rootfs/app/sync_web.py",
        app / "tests/test_sync_engine.py",
        app / "tests/test_sync_web.py",
        app / "docs/FIRST_VERSION.md",
        app / "rootfs/app/adoption.py",
        app / "tests/test_adoption.py",
        app / "rootfs/app/inventory.py",
        app / "rootfs/app/app.py",
        app / "rootfs/app/telemetry.py",
        app / "tests/test_inventory.py",
        app / "icon.png",
        app / "logo.png",
    ])
    config = context["config"]
    registry_path = root / "digitalhouses-stats/digitalhouses_stats/product_registry.json"
    import json
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    product = next((entry for entry in registry.get("products", [])
                    if entry.get("id") == "digitalhouses_sync_app"), None)
    if not product or product.get("telemetry_allowed") is not True:
        fail("DH Sync: product must be admitted to telemetry allowlist")
    if product.get("release") != {
        "title": "DigitalHouses Sync App",
        "version_source": "haos_config",
        "policy_baseline": "0.0.0",
    }:
        fail("DH Sync: canonical release configuration is required")
    # Version and changelog are checked by shared release-readiness rules.
    # Do not freeze the source validator to the initial 0.1.0 release.
    if config.get("slug") != "digitalhouses_sync_app":
        fail("DH Sync: incorrect Supervisor slug")
    maps = config.get("map", [])
    if maps != [{"type": "homeassistant_config", "read_only": False}]:
        fail("DH Sync requires a writable HA configuration bind for automatic YAML sync")
    # Registered dashboards require the official HA WebSocket API. The
    # Supervisor token is used only for the managed DigitalHouses panel.
    if config.get("homeassistant_api") is not True:
        fail("DH Sync requires Home Assistant Core API for Dashboard registration")
    if not config.get("ingress") or config.get("ingress_port") != 8099:
        fail("DH Sync requires admin-only Ingress at port 8099")
    if config.get("panel_admin") is not True:
        fail("DH Sync Ingress must be admin-only")
    if config.get("options", {}).get("telemetry_enabled") is not False:
        fail("DH Sync: fresh HAOS App telemetry must default to false")
    if config.get("schema", {}).get("telemetry_enabled") != "bool":
        fail("DH Sync: telemetry_enabled boolean option is required")
    if "allow_changes" in config.get("options", {}) or "allow_changes" in config.get("schema", {}):
        fail("DH Sync does not use confirmation or change-permission toggles")
