"""PVE Agent resources are source-only, standalone and portable under DH Sync 0.6.0."""
from __future__ import annotations

import json
from pathlib import Path

from app.sync_discovery import build_sync_payload


PRODUCT = Path(__file__).resolve().parents[1]


def _top_level_keys(text: str) -> list[str]:
    return [
        line.split(":", 1)[0]
        for line in text.splitlines()
        if line and not line[0].isspace() and not line.startswith("#") and ":" in line
    ]


def test_mqtt_sync_payload_has_identity_and_no_dashboard_policy():
    version = (PRODUCT / "VERSION").read_text(encoding="utf-8").strip()
    payload = json.loads(build_sync_payload(version))
    assert set(payload) == {
        "schema", "product_id", "type", "version", "repository", "product_path"
    }
    assert payload["product_id"] == "digitalhouses_pve_agent"
    assert payload["version"] == version
    assert payload["product_path"] == "digitalhouses_pve_agent"


def test_pve_and_ups_canonical_views_are_standalone():
    expected_paths = {"dh_pve_agent", "dh_pve_agent_ups"}
    actual_paths: set[str] = set()

    for path in sorted((PRODUCT / "dashboards" / "ru").glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        assert "title" in _top_level_keys(text)
        assert "path" in _top_level_keys(text)
        assert "sections" in _top_level_keys(text)
        assert "views" not in _top_level_keys(text)
        assert "dashboard" not in _top_level_keys(text)
        assert "DH-Dashboard:" not in text
        assert "DH-Order:" not in text
        assert "dh_dashboard_admin_only:" not in text
        view_path = next(
            line.removeprefix("path:").strip()
            for line in text.splitlines()
            if line.startswith("path:")
        )
        assert view_path not in actual_paths
        actual_paths.add(view_path)

    assert actual_paths == expected_paths


def test_canonical_packages_have_unique_keys_and_no_site_delivery():
    common = PRODUCT / "packages" / "common" / "dh_pve_agent_package.yaml"
    ru = PRODUCT / "packages" / "locales" / "ru" / "dh_pve_agent_notification_local_package.yaml"
    common_source = common.read_text(encoding="utf-8")
    ru_source = ru.read_text(encoding="utf-8")

    assert _top_level_keys(common_source) == ["dh_pve_agent_package"]
    assert _top_level_keys(ru_source) == ["dh_pve_agent_notification_local_package"]
    assert "trigger: event.received" in ru_source
    assert "condition: trigger" in ru_source
    assert "action: persistent_notification.create" in ru_source

    for forbidden in (
        "script.write2admins",
        "script.write2log",
        "notify.mobile_app_",
        "notify.telegram",
        "192.168.",
    ):
        assert forbidden not in ru_source
