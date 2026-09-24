from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    ROOT / "examples/packages/dh_app_pve_notification_local_package.yaml",
    ROOT / "examples/packages/locales/ru/dh_app_pve_notification_local_package.yaml",
)

EVENT_TYPES = (
    "problem_started",
    "problem_updated",
    "problem_recovered",
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


def test_local_notification_packages_trigger_on_all_supported_machine_events():
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        for event_type in EVENT_TYPES:
            assert f"- {event_type}" in text
            assert f"id: {event_type}" in text


def test_local_notification_packages_read_machine_fields_directly():
    required = (
        "object_name",
        "metric",
        "current.value",
        "crossed_thresholds",
        "current_charge_percent",
        "reason",
        "battery_charge_percent",
        "battery_runtime_seconds",
        "old_values",
        "new_values",
    )
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        for field in required:
            assert field in text, f"{path}: missing machine field {field}"


def test_local_notification_packages_do_not_reimplement_machine_schema_validation():
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")

        for forbidden in (
            "schema_version ==",
            "is mapping",
            "is number",
            "is string",
            "contract_error",
            "failure_class",
            "notification_schema_version",
        ):
            assert forbidden not in text


def test_local_notification_packages_use_direct_actions():
    en = PACKAGES[0].read_text(encoding="utf-8")
    ru = PACKAGES[1].read_text(encoding="utf-8")

    assert "action: persistent_notification.create" in en
    assert "action: script.write2log" in ru

    assert "event: dh_app_pve_notification" not in en
    assert "event: dh_app_pve_notification" not in ru
