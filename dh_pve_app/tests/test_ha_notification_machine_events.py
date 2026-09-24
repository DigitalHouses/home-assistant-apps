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
    "ups_status_changed",
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
        "previous_status",
        "current_status",
        "crossed_thresholds",
        "previous_charge_percent",
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
