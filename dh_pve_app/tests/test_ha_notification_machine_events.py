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

        assert "{% if schema == 1 %}" in live
        assert "trigger.to_state.attributes.summary" in live
        assert "trigger.to_state.attributes.details" in live
        assert "{% elif kind in ['problem_started', 'problem_updated', 'problem_recovered'] %}" in live
        assert "trigger.to_state.attributes.current | default({}, true)" in live
        assert "current.get('value')" in live
        assert "current.get('average')" in live
        assert "current.get('threshold')" in live

        v2_problem_branch = live.split(
            "{% elif kind in ['problem_started', 'problem_updated', 'problem_recovered'] %}",
            1,
        )[1].split("{% elif kind == 'ups_status_changed' %}", 1)[0]
        assert "trigger.to_state.attributes.summary" not in v2_problem_branch
        assert "trigger.to_state.attributes.details" not in v2_problem_branch


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
