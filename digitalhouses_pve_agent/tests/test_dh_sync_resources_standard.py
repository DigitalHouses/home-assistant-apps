"""PVE producer guard for the sole DH Sync Resources Standard (0.4+).

DH Sync auto-installs published YAML without an Apply button. Protect exact
publication scope and stable HA identities; examples are not auto-resources.
No new dependency on a YAML parser is imposed on the Linux agent's CI.
"""
from __future__ import annotations

import re
from pathlib import Path


PRODUCT = Path(__file__).resolve().parents[1]
ROOT = PRODUCT.parent
STANDARD = ROOT / "docs" / "standards" / "DH_SYNC_RESOURCES_STANDARD.md"
VIEWS = PRODUCT / "dashboards" / "ru"
COMMON = PRODUCT / "packages" / "common"
RU_LOCALES = PRODUCT / "packages" / "locales" / "ru"
EXAMPLES = PRODUCT / "examples" / "packages"

EXPECTED_VIEWS = {
    "10_pve_proxmox.yaml": ("dh_pve_agent", "Proxmox", "mdi:server"),
    "11_pve_ups.yaml": ("dh_pve_agent_ups", "Электропитание", "mdi:power-plug-battery"),
}
EXPECTED_COMMON_PACKAGE = "dh_pve_agent_package.yaml"
EXPECTED_PACKAGE_KEY = "dh_pve_agent_package"


def _top_level_values(source: str) -> dict[str, str]:
    """Extract only unindented literal YAML scalar declarations."""
    values: dict[str, str] = {}
    for line in source.splitlines():
        if not line or line.startswith("#") or line[0].isspace():
            continue
        key, delimiter, value = line.partition(":")
        if delimiter:
            assert key not in values, f"duplicate top-level field: {key}"
            values[key] = value.strip()
    return values


def _package_keys(source: str) -> set[str]:
    """Top-level package names, not nested HA domains/actions."""
    return set(re.findall(r"^([a-z][a-z0-9_]*):\s*(?:#.*)?$", source, re.MULTILINE))


def test_standard_is_the_single_normative_resource_contract() -> None:
    text = STANDARD.read_text(encoding="utf-8")
    for phrase in (
        "dashboards/ru/*.yaml",
        "packages/common/*.yaml",
        "packages/locales/ru/*.yaml",
        "examples/",
        "автоматически",
    ):
        assert phrase in text
    product = (PRODUCT / "docs" / "DH_SYNC_RESOURCES.md").read_text(encoding="utf-8")
    readme = (PRODUCT / "README.md").read_text(encoding="utf-8")
    discovery = (PRODUCT / "docs" / "DH_SYNC_DISCOVERY_V1.md").read_text(encoding="utf-8")
    for doc in (product, readme, discovery):
        assert "DH_SYNC_RESOURCES_STANDARD.md" in doc
    assert "No manual Apply" in product


def test_only_two_accepted_ru_views_are_auto_published() -> None:
    published = {p.name for p in VIEWS.glob("*.yaml")}
    assert published == set(EXPECTED_VIEWS)
    paths: set[str] = set()
    for filename, (path, title, icon) in EXPECTED_VIEWS.items():
        yaml = (VIEWS / filename).read_text(encoding="utf-8")
        values = _top_level_values(yaml)
        assert values["path"] == path
        assert values["title"] == title
        assert values["icon"] == icon
        assert values["type"] == "sections"
        assert values["show_icon_and_title"] == "false"
        assert values.get("lovelace") is None
        assert values.get("views") is None
        assert yaml.count("path: " + path + "\n") == 1
        assert path not in paths
        paths.add(path)
    assert not list((PRODUCT / "dashboards" / "en").glob("*.yaml"))


def test_common_package_is_portable_and_matches_existing_ha_contract() -> None:
    assert {p.name for p in COMMON.glob("*.yaml")} == {EXPECTED_COMMON_PACKAGE}
    canonical = (COMMON / EXPECTED_COMMON_PACKAGE).read_text(encoding="utf-8")
    example = (EXAMPLES / EXPECTED_COMMON_PACKAGE).read_text(encoding="utf-8")
    assert _package_keys(canonical) == {EXPECTED_PACKAGE_KEY}
    assert canonical.split("\n", 4)[4] == example  # exact existing HA identities
    for field in ("  recorder:", "  logbook:", "  input_select:", "  input_number:", "  script:"):
        assert field in canonical
    for forbidden in (
        "script.write2admins",
        "notify.",
        "192.168.",
        "secrets.yaml",
        "\n  template:",
    ):
        assert forbidden not in canonical


def test_site_specific_notification_variants_cannot_be_auto_published() -> None:
    assert not list(RU_LOCALES.glob("*.yaml")), (
        "New RU notifications become auto-installed on every discovered home; "
        "review portability, existing package keys and automation IDs first."
    )
    portable = EXAMPLES / "locales" / "ru" / "dh_pve_agent_notification_local_package.yaml"
    custom = EXAMPLES / "locales" / "ru" / "dh_pve_agent_notification_write2admins.yaml"
    assert portable.exists() and custom.exists()
    assert _package_keys(portable.read_text(encoding="utf-8")) == {
        "dh_pve_agent_notification_local_package"
    }
    assert _package_keys(custom.read_text(encoding="utf-8")) == {
        "dh_pve_agent_notification_local_package"
    }
    assert "action: persistent_notification.create" in portable.read_text(encoding="utf-8")
    assert "script.write2admins" in custom.read_text(encoding="utf-8")


def test_existing_mqtt_discovery_remains_required_but_not_replaced() -> None:
    topics = (PRODUCT / "app" / "topics.py").read_text(encoding="utf-8")
    mqtt = (PRODUCT / "app" / "mqtt_bridge.py").read_text(encoding="utf-8")
    sync = (PRODUCT / "app" / "sync_discovery.py").read_text(encoding="utf-8")
    assert "sync" in topics
    assert "build_sync_payload" in mqtt
    assert "https://github.com/DigitalHouses/home-assistant-apps" in sync
    assert "digitalhouses_pve_agent" in sync
    assert "packages/locales/ru" in (PRODUCT / "docs" / "DH_SYNC_RESOURCES.md").read_text()
