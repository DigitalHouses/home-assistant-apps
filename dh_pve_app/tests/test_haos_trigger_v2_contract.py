from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "examples" / "dh_app_pve_ups_dashboard.yaml"
UI_PACKAGE = ROOT / "examples" / "packages" / "dh_app_pve_ui_package.yaml"
NOTIFICATION_PACKAGE = ROOT / "examples" / "packages" / "dh_app_pve_notification_package.yaml"


def test_trigger_dashboard_has_view_edit_confirm_apply_flow():
    text = DASHBOARD.read_text(encoding="utf-8")
    for token in (
        "Config UPS trigger",
        "input_select.dh_app_pve_ups_trigger_ui_state",
        "state: view",
        "state: edit",
        "state: confirm",
        "script.dh_app_pve_ups_trigger_open",
        "script.dh_app_pve_ups_trigger_cancel",
        "script.dh_app_pve_ups_trigger_review",
        "script.dh_app_pve_ups_trigger_apply",
        "sensor.dh_app_pve_ups_trigger_policy",
        "active_charge_threshold_percent",
        "active_runtime_reserve_seconds",
        "number.dh_app_pve_ups_shutdown_battery_charge_threshold",
        "number.dh_app_pve_ups_shutdown_runtime_reserve",
        "sensor.dh_app_pve_ups_guest_shutdown_budget",
        "sensor.dh_app_pve_ups_shutdown_budget",
        "sensor.dh_app_pve_ups_shutdown_readiness",
    ):
        assert token in text
    assert "sensor.dh_app_pve_ups_policy_on_battery_delay" not in text
    assert "custom:auto-entities" not in text


def test_ui_package_snapshots_real_active_policy_reverts_cancel_and_closes_on_success():
    assert UI_PACKAGE.exists()
    text = UI_PACKAGE.read_text(encoding="utf-8")
    for token in (
        "dh_app_pve_ups_trigger_ui_state:",
        "- view",
        "- edit",
        "- confirm",
        "dh_app_pve_ups_trigger_snapshot_charge:",
        "dh_app_pve_ups_trigger_snapshot_reserve:",
        "dh_app_pve_ups_trigger_open:",
        "dh_app_pve_ups_trigger_cancel:",
        "dh_app_pve_ups_trigger_review:",
        "dh_app_pve_ups_trigger_apply:",
        "sensor.dh_app_pve_ups_trigger_policy",
        "active_charge_threshold_percent",
        "active_runtime_reserve_seconds",
        "number.set_value",
        "button.press",
        "trigger: event.received",
        "config_changed",
    ):
        assert token in text
    assert "script.write2log" not in text
    assert "notify.mobile_app" not in text


def test_notification_package_uses_events_gate_and_retained_aggregates_only():
    assert NOTIFICATION_PACKAGE.exists()
    text = NOTIFICATION_PACKAGE.read_text(encoding="utf-8")
    for token in (
        "event.dh_app_pve_diagnostic",
        "event.dh_app_pve_ups_diagnostic",
        "binary_sensor.bs_global_system_boot_completed",
        "sensor.dh_app_pve_problems",
        "sensor.dh_app_pve_ups_problems",
        "problem_started",
        "problem_updated",
        "problem_recovered",
        "config_changed",
        "event: dh_app_pve_notification",
        "trigger: event.received",
        "state_attr('sensor.dh_app_pve_problems', 'summary')",
        "state_attr('sensor.dh_app_pve_problems', 'active')",
        "state_attr('sensor.dh_app_pve_ups_problems', 'summary')",
        "state_attr('sensor.dh_app_pve_ups_problems', 'active')",
    ):
        assert token in text
    for forbidden in (
        "states.sensor",
        "states.binary_sensor",
        "custom:auto-entities",
        "script.write2log",
        "notify.mobile_app",
        "time_pattern",
    ):
        assert forbidden not in text


def test_live_notification_presentation_is_localized_from_structured_event_fields():
    text = NOTIFICATION_PACKAGE.read_text(encoding="utf-8")
    for token in (
        "trigger.to_state.attributes.metric",
        "trigger.to_state.attributes.value",
        "trigger.to_state.attributes.average",
        "trigger.to_state.attributes.threshold",
        "Температура",
        "Занято",
        "Троттлинг",
        "SMART",
        "обнаружена проблема",
        "параметры проблемы изменились",
        "состояние нормализовалось",
    ):
        assert token in text
