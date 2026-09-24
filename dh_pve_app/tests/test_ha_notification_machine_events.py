from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    ROOT / "examples/packages/dh_app_pve_notification_package.yaml",
    ROOT / "examples/packages/locales/ru/dh_app_pve_notification_package.yaml",
)

STATUS_TRANSITIONS = (
    "on_battery",
    "boost",
    "trim",
    "bypass",
    "overload",
    "low_battery",
    "replace_battery",
)


def test_notification_packages_accept_machine_event_v2_types():
    required = {
        "ups_status_changed",
        "battery_discharge_level_crossed",
        "battery_fully_charged",
        "shutdown_committed",
        "config_changed",
    }
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        assert "schema_version" in text
        for event_type in required:
            assert event_type in text


def test_notification_packages_have_v2_machine_fields():
    required = (
        "previous_status",
        "current_status",
        "previous_raw_status",
        "current_raw_status",
        "crossed_thresholds",
        "previous_charge_percent",
        "current_charge_percent",
        "previous_charger_status",
        "current_charger_status",
        "reason",
        "battery_charge_percent",
        "battery_runtime_seconds",
        "shutdown_budget_seconds",
        "runtime_reserve_seconds",
        "runtime_guard_threshold_seconds",
        "old_values",
        "new_values",
        "previous_revision",
        "current_revision",
    )
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        for field in required:
            assert field in text, f"{path}: missing v2 machine field {field}"


def test_v2_status_notifications_cover_canonical_enter_and_exit_transitions():
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        for status in STATUS_TRANSITIONS:
            assert (
                f"'{status}' in current_status and '{status}' not in previous_status" in text
            ), f"{path}: missing {status} enter mapping"
            assert (
                f"'{status}' in previous_status and '{status}' not in current_status" in text
            ), f"{path}: missing {status} exit mapping"


def test_v2_live_problem_branch_uses_machine_fields_not_app_prose():
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        live = text.split("- id: dh_app_pve_ups_config_changed_notification", 1)[0]

        assert "attrs.schema_version == 1" in live
        assert "trigger.to_state.attributes.get('summary')" in live
        assert "trigger.to_state.attributes.get('details')" in live
        assert "attrs.schema_version == 2" in live
        assert "attrs.current is mapping" in live
        assert "current['value']" in live
        assert "current['average']" in live
        assert "current['threshold']" in live


def test_shutdown_committed_and_config_changed_use_structured_v2_fields():
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        for field in (
            "reason",
            "battery_charge_percent",
            "battery_runtime_seconds",
            "shutdown_budget_seconds",
            "runtime_reserve_seconds",
            "runtime_guard_threshold_seconds",
        ):
            assert f"trigger.to_state.attributes.{field}" in text

        for field in (
            "old_values",
            "new_values",
            "previous_revision",
            "current_revision",
        ):
            assert f"trigger.to_state.attributes.{field}" in text


def _machine_event_blocks(text: str) -> tuple[str, str]:
    live, remainder = text.split(
        "- id: dh_app_pve_ups_config_changed_notification",
        1,
    )
    config_changed = remainder.split(
        "- id: dh_app_pve_startup_problem_reconciliation",
        1,
    )[0]
    return live, config_changed


def test_machine_event_notification_contract_has_no_silent_defaults():
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        live, config_changed = _machine_event_blocks(text)

        for block in (live, config_changed):
            assert "| default(" not in block, (
                f"{path}: machine-event contract must not silently default missing fields"
            )
            assert "| int(1)" not in block, (
                f"{path}: schema_version must be required, not defaulted"
            )


def test_live_machine_events_use_event_specific_contract_branches():
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        live, _config_changed = _machine_event_blocks(text)

        assert "choose:" in live
        for event_type in (
            "problem_started",
            "problem_updated",
            "problem_recovered",
            "ups_status_changed",
            "battery_discharge_level_crossed",
            "battery_fully_charged",
            "shutdown_committed",
        ):
            assert event_type in live

        assert "kind: contract_error" in live
        assert "severity: error" in live


def test_config_changed_contract_has_explicit_contract_error_path():
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        _live, config_changed = _machine_event_blocks(text)

        assert "kind: contract_error" in config_changed
        assert "severity: error" in config_changed


def test_battery_fully_charged_contract_does_not_read_unrelated_problem_fields():
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        live, _config_changed = _machine_event_blocks(text)
        charged = live.split(
            "attrs.event_type == 'battery_fully_charged'",
            1,
        )[1].split(
            "attrs.event_type == 'shutdown_committed'",
            1,
        )[0]

        for unrelated in (
            "active_problem_count",
            "current_status",
            "current_raw_status",
            "shutdown_budget_seconds",
            "runtime_reserve_seconds",
        ):
            assert unrelated not in charged, (
                f"{path}: battery_fully_charged must not read unrelated field {unrelated}"
            )
