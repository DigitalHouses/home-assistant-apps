import pytest

from app.ups_policy import (
    PolicyValidationError,
    UpsPolicyDraft,
    migrate_legacy_policy_state,
    parse_policy_value,
    policy_hash,
)


def test_v2_policy_contains_only_software_trigger_settings():
    draft = UpsPolicyDraft(
        shutdown_battery_charge_threshold_percent=20,
        runtime_reserve_seconds=180,
    )

    assert draft.as_dict() == {
        "shutdown_battery_charge_threshold_percent": 20,
        "runtime_reserve_seconds": 180,
    }
    assert not hasattr(draft, "on_battery_delay_minutes")
    assert not hasattr(draft, "power_restore_delay_seconds")
    assert len(policy_hash(draft)) == 64


def test_v2_policy_backend_ranges_are_explicit_and_step_validated():
    for value in (10, 15, 20, 25, 30):
        assert parse_policy_value(
            "shutdown_battery_charge_threshold_percent", str(value)
        ) == value

    for value in (60, 180, 900):
        assert parse_policy_value("runtime_reserve_seconds", str(value)) == value

    for key, value in (
        ("shutdown_battery_charge_threshold_percent", "9"),
        ("shutdown_battery_charge_threshold_percent", "11"),
        ("shutdown_battery_charge_threshold_percent", "31"),
        ("runtime_reserve_seconds", "0"),
        ("runtime_reserve_seconds", "61"),
        ("runtime_reserve_seconds", "901"),
    ):
        with pytest.raises(PolicyValidationError):
            parse_policy_value(key, value)


def test_legacy_timer_is_never_migrated_into_runtime_reserve():
    migrated = migrate_legacy_policy_state(
        {
            "on_battery_delay_minutes": 30,
            "power_restore_delay_seconds": 120,
        },
        shutdown_battery_charge_threshold_percent=20,
    )

    assert migrated == UpsPolicyDraft(
        shutdown_battery_charge_threshold_percent=20,
        runtime_reserve_seconds=180,
    )


def test_legacy_migration_requires_valid_charge_threshold_source():
    assert (
        migrate_legacy_policy_state(
            {"on_battery_delay_minutes": 30},
            shutdown_battery_charge_threshold_percent=None,
        )
        is None
    )
    assert (
        migrate_legacy_policy_state(
            {"on_battery_delay_minutes": 30},
            shutdown_battery_charge_threshold_percent=11,
        )
        is None
    )
