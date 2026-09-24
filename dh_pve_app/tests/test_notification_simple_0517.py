from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "dh_pve_app"
PACKAGES = APP / "examples" / "packages"
EN = PACKAGES / "dh_app_pve_notification_local_package.yaml"
RU = PACKAGES / "locales" / "ru" / "dh_app_pve_notification_local_package.yaml"
OLD_EN = PACKAGES / "dh_app_pve_notification_package.yaml"
OLD_RU = PACKAGES / "locales" / "ru" / "dh_app_pve_notification_package.yaml"
STANDARD = ROOT / "docs" / "standards" / "EVENTS_AND_NOTIFICATIONS_STANDARD.md"

TRIGGER_IDS = (
    "problem_started",
    "problem_updated",
    "problem_recovered",
    "ups_status_changed",
    "battery_discharge_level_crossed",
    "battery_fully_charged",
    "shutdown_committed",
    "config_changed",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def test_notification_local_package_is_direct_and_readable() -> None:
    assert not OLD_EN.exists()
    assert not OLD_RU.exists()

    for path in (EN, RU):
        text = _read(path)

        assert "trigger: event.received" in text
        assert "condition: trigger" in text
        assert "trigger.to_state.attributes" in text

        for trigger_id in TRIGGER_IDS:
            assert f"id: {trigger_id}" in text

        for forbidden in (
            "event: dh_app_pve_notification",
            "notification_schema_version",
            "contract_error",
            "failure_class",
            "source_schema_version",
            "startup_problem_reconciliation",
            "attrs.schema_version",
            "is mapping",
            "is number",
        ):
            assert forbidden not in text


def test_notification_local_package_calls_delivery_directly() -> None:
    en = _read(EN)
    ru = _read(RU)

    assert "action: persistent_notification.create" in en
    assert "action: script.write2log" in ru


def test_notification_standard_uses_simple_direct_flow() -> None:
    text = _read(STANDARD)

    assert "machine event" in text
    assert "trigger.id" in text
    assert "choose" in text
    assert "direct action" in text

    for forbidden in (
        "Notification Envelope",
        "localized notification event",
        "contract_error",
        "delivery adapter",
    ):
        assert forbidden not in text
