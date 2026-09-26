from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "digitalhouses_pve_agent"
PACKAGES = APP / "examples" / "packages"
EN = PACKAGES / "dh_pve_agent_notification_local_package.yaml"
RU = PACKAGES / "locales" / "ru" / "dh_pve_agent_notification_local_package.yaml"
OLD_EN = PACKAGES / "dh_pve_agent_notification_package.yaml"
OLD_RU = PACKAGES / "locales" / "ru" / "dh_pve_agent_notification_package.yaml"
STANDARD = ROOT / "docs" / "standards" / "EVENTS_AND_NOTIFICATIONS_STANDARD.md"

TRIGGER_IDS = (
    "cpu_temperature_high",
    "cpu_temperature_normal",
    "cpu_throttling_started",
    "cpu_throttling_cleared",
    "storage_usage_high",
    "storage_usage_normal",
    "disk_temperature_high",
    "disk_temperature_normal",
    "gpu_temperature_high",
    "gpu_temperature_normal",
    "fan_control_restore_failed",
    "fan_control_restored",
    "disk_smart_failed",
    "disk_smart_restored",
    "nut_unavailable",
    "nut_restored",
    "power_state_unknown",
    "power_state_restored",
    "line_power_lost",
    "line_power_restored",
    "low_battery_started",
    "low_battery_cleared",
    "high_battery_started",
    "high_battery_cleared",
    "replace_battery_started",
    "replace_battery_cleared",
    "bypass_started",
    "bypass_ended",
    "calibration_started",
    "calibration_ended",
    "output_off",
    "output_restored",
    "overload_started",
    "overload_cleared",
    "trim_started",
    "trim_ended",
    "boost_started",
    "boost_ended",
    "forced_shutdown_started",
    "forced_shutdown_cleared",
    "alarm_started",
    "alarm_cleared",
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
            "event: dh_pve_agent_notification",
            "notification_schema_version",
            "contract_error",
            "failure_class",
            "source_schema_version",
            "startup_problem_reconciliation",
            "attrs.schema_version",
            "is mapping",
        ):
            assert forbidden not in text


def test_notification_local_package_calls_delivery_directly() -> None:
    en = _read(EN)
    ru = _read(RU)

    assert "action: persistent_notification.create" in en
    assert "action: persistent_notification.create" in ru


def test_notification_standard_uses_simple_direct_flow() -> None:
    text = _read(STANDARD)

    assert "machine event" in text
    assert "trigger.id" in text
    assert "choose" in text
    assert "direct action" in text

    assert "There is no intermediate DigitalHouses notification protocol." in text
    assert "call the final delivery action directly" in text
