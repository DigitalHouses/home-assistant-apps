from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "examples" / "dh_app_pve_ups_dashboard.yaml"
UI_PACKAGE = ROOT / "examples" / "packages" / "dh_app_pve_package.yaml"
LEGACY_UI_PACKAGE = ROOT / "examples" / "packages" / "dh_app_pve_ui_package.yaml"
NOTIFICATION_PACKAGE = ROOT / "examples" / "packages" / "dh_app_pve_notification_local_package.yaml"
RU_NOTIFICATION_PACKAGE = (
    ROOT
    / "examples"
    / "packages"
    / "locales"
    / "ru"
    / "dh_app_pve_notification_local_package.yaml"
)


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


def test_ui_helpers_are_consolidated_into_base_package():
    assert UI_PACKAGE.exists()
    assert not LEGACY_UI_PACKAGE.exists()


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


def test_ui_open_and_cancel_wait_for_app_owned_draft_ack_before_state_transition():
    text = UI_PACKAGE.read_text(encoding="utf-8")
    open_section = text.split("    dh_app_pve_ups_trigger_open:", 1)[1].split(
        "    dh_app_pve_ups_trigger_cancel:", 1
    )[0]
    cancel_section = text.split("    dh_app_pve_ups_trigger_cancel:", 1)[1].split(
        "    dh_app_pve_ups_trigger_review:", 1
    )[0]

    for section, final_option in ((open_section, "edit"), (cancel_section, "view")):
        assert "wait_template:" in section
        assert "draft_charge_threshold_percent" in section
        assert "draft_runtime_reserve_seconds" in section
        assert 'timeout: "00:00:30"' in section
        assert "continue_on_timeout: true" in section
        assert "error: true" in section
        assert section.index("wait_template:") < section.index(f"option: {final_option}")

    assert "delay:" not in open_section
    assert "delay:" not in cancel_section


def test_notification_package_uses_simple_event_trigger_flow():
    assert NOTIFICATION_PACKAGE.exists()
    text = NOTIFICATION_PACKAGE.read_text(encoding="utf-8")

    for token in (
        "event.dh_app_pve_diagnostic",
        "event.dh_app_pve_ups_diagnostic",
        "trigger: event.received",
        "condition: trigger",
        "trigger.to_state.attributes",
        "id: cpu_temperature_high",
        "id: cpu_temperature_normal",
        "id: cpu_throttling_started",
        "id: storage_usage_high",
        "id: disk_smart_failed",
        "id: line_power_lost",
        "id: boost_started",
        "id: config_changed",
    ):
        assert token in text

    for forbidden in (
        "event: dh_app_pve_notification",
        "notification_schema_version",
        "contract_error",
        "startup_problem_reconciliation",
        "binary_sensor.bs_global_system_boot_completed",
        "time_pattern",
    ):
        assert forbidden not in text


def test_russian_notification_package_calls_write2log_directly():
    assert RU_NOTIFICATION_PACKAGE.exists()
    text = RU_NOTIFICATION_PACKAGE.read_text(encoding="utf-8")

    assert "action: script.write2log" in text
    assert "высокая температура CPU" in text
    assert "CPU throttling" in text
    assert "заполнение хранилища" in text
    assert "Входное напряжение" in text or "входное напряжение" in text
    assert "батарея заряжена" in text


def test_config_changed_notification_is_direct_and_localized():
    assert RU_NOTIFICATION_PACKAGE.exists()
    text = RU_NOTIFICATION_PACKAGE.read_text(encoding="utf-8")

    assert "id: config_changed" in text
    assert "Конфигурация UPS Trigger изменена" in text
    assert "trigger.to_state.attributes.old_values" in text
    assert "trigger.to_state.attributes.new_values" in text


def test_ui_closes_trigger_editor_only_for_valid_v2_config_changed_contract():
    text = UI_PACKAGE.read_text(encoding="utf-8")
    section = text.split(
        "- id: dh_app_pve_ups_trigger_close_after_success",
        1,
    )[1]

    for token in (
        "condition: template",
        "'event_type' in attrs",
        "attrs.event_type == 'config_changed'",
        "'schema_version' in attrs",
        "attrs.schema_version == 2",
        "'observed_at' in attrs",
        "attrs.observed_at is string",
        "'old_values' in attrs",
        "attrs.old_values is mapping",
        "'new_values' in attrs",
        "attrs.new_values is mapping",
        "'shutdown_battery_charge_threshold_percent' in attrs.new_values",
        "attrs.new_values.shutdown_battery_charge_threshold_percent is number",
        "'runtime_reserve_seconds' in attrs.new_values",
        "attrs.new_values.runtime_reserve_seconds is number",
        "'previous_revision' in attrs",
        "attrs.previous_revision is number",
        "'current_revision' in attrs",
        "attrs.current_revision is number",
    ):
        assert token in section

    assert section.index("condition: template") < section.index("option: view")


def test_ui_numeric_contract_is_validated_before_float_conversion():
    text = UI_PACKAGE.read_text(encoding="utf-8")
    open_section = text.split("    dh_app_pve_ups_trigger_open:", 1)[1].split(
        "    dh_app_pve_ups_trigger_cancel:", 1
    )[0]
    cancel_section = text.split("    dh_app_pve_ups_trigger_cancel:", 1)[1].split(
        "    dh_app_pve_ups_trigger_review:", 1
    )[0]
    apply_section = text.split("    dh_app_pve_ups_trigger_apply:", 1)[1].split(
        "  automation:", 1
    )[0]

    for token in (
        "is_number(active_charge)",
        "is_number(active_reserve)",
        "is_number(draft_charge)",
        "is_number(draft_reserve)",
    ):
        assert token in open_section

    for token in (
        "snapshot_charge:",
        "snapshot_reserve:",
        "is_number(snapshot_charge)",
        "is_number(snapshot_reserve)",
        "is_number(draft_charge)",
        "is_number(draft_reserve)",
    ):
        assert token in cancel_section

    for token in (
        "current_charge_raw:",
        "current_reserve_raw:",
        "active_charge_raw:",
        "active_reserve_raw:",
        "is_number(current_charge_raw)",
        "is_number(current_reserve_raw)",
        "is_number(active_charge_raw)",
        "is_number(active_reserve_raw)",
    ):
        assert token in apply_section

    for unsafe in (
        "states('number.dh_app_pve_ups_shutdown_battery_charge_threshold') | float",
        "states('number.dh_app_pve_ups_shutdown_runtime_reserve') | float",
        "states('input_number.dh_app_pve_ups_trigger_snapshot_charge') | float",
        "states('input_number.dh_app_pve_ups_trigger_snapshot_reserve') | float",
    ):
        assert unsafe not in text


def test_ui_contract_failures_stop_explicitly_instead_of_coercing_values():
    text = UI_PACKAGE.read_text(encoding="utf-8")

    assert text.count("DH PVE UPS Trigger UI contract error:") >= 4
    assert text.count("error: true") >= 4
    assert "acknowledgement timeout" in text
    assert "missing or invalid" in text
