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

        assert "attrs.schema_version == 1" not in live
        assert "trigger.to_state.attributes.get('summary')" not in live
        assert "trigger.to_state.attributes.get('details')" not in live
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


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


V2_REQUIRED_FIELDS = {
    "problem": (
        "observed_at",
        "problem_id",
        "category",
        "severity",
        "object_id",
        "object_name",
        "metric",
        "previous",
        "current",
        "active_problem_count",
    ),
    "ups_status_changed": (
        "observed_at",
        "previous_status",
        "current_status",
        "previous_raw_status",
        "current_raw_status",
    ),
    "battery_discharge_level_crossed": (
        "observed_at",
        "previous_charge_percent",
        "current_charge_percent",
        "crossed_thresholds",
    ),
    "battery_fully_charged": (
        "observed_at",
        "previous_charge_percent",
        "current_charge_percent",
        "previous_charger_status",
        "current_charger_status",
        "detection_source",
    ),
    "shutdown_committed": (
        "observed_at",
        "reason",
        "battery_charge_percent",
        "battery_runtime_seconds",
        "shutdown_budget_seconds",
        "runtime_reserve_seconds",
        "runtime_guard_threshold_seconds",
    ),
}


def _v2_live_branches(live: str) -> dict[str, str]:
    problem_start = (
        "attrs.schema_version == 2\n"
        "                       and attrs.event_type in "
        "['problem_started', 'problem_updated', 'problem_recovered']"
    )
    status_start = "attrs.event_type == 'ups_status_changed'"
    discharge_start = "attrs.event_type == 'battery_discharge_level_crossed'"
    charged_start = "attrs.event_type == 'battery_fully_charged'"
    shutdown_start = "attrs.event_type == 'shutdown_committed'"
    return {
        "problem": _between(live, problem_start, status_start),
        "ups_status_changed": _between(live, status_start, discharge_start),
        "battery_discharge_level_crossed": _between(
            live, discharge_start, charged_start
        ),
        "battery_fully_charged": _between(live, charged_start, shutdown_start),
        "shutdown_committed": live.split(shutdown_start, 1)[1].split(
            "          default:", 1
        )[0],
    }


def test_each_v2_machine_schema_rejects_every_missing_required_field():
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        live, _config_changed = _machine_event_blocks(text)
        branches = _v2_live_branches(live)

        assert live.count("'event_type' in attrs") >= len(V2_REQUIRED_FIELDS)
        assert live.count("'schema_version' in attrs") >= len(V2_REQUIRED_FIELDS)

        for schema, required_fields in V2_REQUIRED_FIELDS.items():
            branch = branches[schema]
            for field in required_fields:
                assert f"'{field}' in attrs" in branch, (
                    f"{path}: {schema} must reject missing required field {field}"
                )

        assert "kind: contract_error" in live


def test_v2_machine_schema_guards_reject_invalid_required_types():
    required_type_guards = {
        "problem": (
            "attrs.observed_at is string",
            "attrs.current is mapping",
            "attrs.active_problem_count is number",
            "attrs.active_problem_count >= 0",
        ),
        "ups_status_changed": (
            "attrs.observed_at is string",
            "attrs.previous_status is sequence",
            "attrs.previous_status is not string",
            "attrs.current_status is sequence",
            "attrs.current_status is not string",
        ),
        "battery_discharge_level_crossed": (
            "attrs.previous_charge_percent is number",
            "attrs.current_charge_percent is number",
            "attrs.crossed_thresholds is sequence",
            "attrs.crossed_thresholds is not string",
        ),
        "battery_fully_charged": (
            "attrs.previous_charge_percent is number or attrs.previous_charge_percent is none",
            "attrs.current_charge_percent is number or attrs.current_charge_percent is none",
            "attrs.previous_charger_status is string",
            "attrs.current_charger_status is string",
            "attrs.detection_source is string",
        ),
        "shutdown_committed": (
            "attrs.reason is string",
            "attrs.battery_charge_percent is number or attrs.battery_charge_percent is none",
            "attrs.battery_runtime_seconds is number or attrs.battery_runtime_seconds is none",
            "attrs.shutdown_budget_seconds is number or attrs.shutdown_budget_seconds is none",
            "attrs.runtime_reserve_seconds is number or attrs.runtime_reserve_seconds is none",
            "attrs.runtime_guard_threshold_seconds is number or attrs.runtime_guard_threshold_seconds is none",
        ),
    }

    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        live, _config_changed = _machine_event_blocks(text)
        branches = _v2_live_branches(live)

        for schema, guards in required_type_guards.items():
            for guard in guards:
                assert guard in branches[schema], (
                    f"{path}: {schema} missing type guard {guard}"
                )


def test_config_changed_rejects_missing_or_invalid_required_fields():
    required = (
        "event_type",
        "schema_version",
        "observed_at",
        "old_values",
        "new_values",
        "previous_revision",
        "current_revision",
    )
    guards = (
        "attrs.observed_at is string",
        "attrs.old_values is mapping",
        "attrs.new_values is mapping",
        "attrs.new_values.shutdown_battery_charge_threshold_percent is number",
        "attrs.new_values.runtime_reserve_seconds is number",
        "attrs.previous_revision is number",
        "attrs.current_revision is number",
    )

    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        _live, config_changed = _machine_event_blocks(text)

        for field in required:
            assert f"'{field}' in attrs" in config_changed, (
                f"{path}: config_changed must reject missing field {field}"
            )
        for guard in guards:
            assert guard in config_changed, (
                f"{path}: config_changed missing type guard {guard}"
            )
        assert "kind: contract_error" in config_changed
