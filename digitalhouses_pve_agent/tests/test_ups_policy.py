import pytest

from app.ups_policy import (
    GuestShutdownTask,
    PolicyValidationError,
    UpsPolicyDraft,
    calculate_guest_shutdown_budget,
    parse_policy_value,
    policy_hash,
    validate_policy,
)


def test_parse_policy_values_accepts_only_v2_ranges_and_steps():
    assert parse_policy_value("shutdown_battery_charge_threshold_percent", "20") == 20
    assert parse_policy_value("runtime_reserve_seconds", "180") == 180

    for key, value in (
        ("shutdown_battery_charge_threshold_percent", "9"),
        ("shutdown_battery_charge_threshold_percent", "11"),
        ("shutdown_battery_charge_threshold_percent", "31"),
        ("runtime_reserve_seconds", "0"),
        ("runtime_reserve_seconds", "61"),
        ("runtime_reserve_seconds", "901"),
        ("runtime_reserve_seconds", "abc"),
        ("on_battery_delay_minutes", "30"),
        ("power_restore_delay_seconds", "120"),
        ("unknown", "10"),
    ):
        with pytest.raises(PolicyValidationError):
            parse_policy_value(key, value)


def test_policy_hash_is_stable_and_depends_only_on_v2_policy_values():
    first = UpsPolicyDraft(20, 180)
    same = UpsPolicyDraft(20, 180)
    changed_charge = UpsPolicyDraft(25, 180)
    changed_reserve = UpsPolicyDraft(20, 240)

    assert policy_hash(first) == policy_hash(same)
    assert len(policy_hash(first)) == 64
    assert policy_hash(first) != policy_hash(changed_charge)
    assert policy_hash(first) != policy_hash(changed_reserve)


def test_guest_shutdown_budget_matches_current_pve_policy_groups():
    tasks = (
        GuestShutdownTask(vmid=501, order=50, timeout_seconds=30),
        GuestShutdownTask(vmid=200, order=50, timeout_seconds=30),
        GuestShutdownTask(vmid=333, order=50, timeout_seconds=30),
        GuestShutdownTask(vmid=1011, order=40, timeout_seconds=30),
        GuestShutdownTask(vmid=10001, order=40, timeout_seconds=30),
        GuestShutdownTask(vmid=10004, order=40, timeout_seconds=30),
        GuestShutdownTask(vmid=110, order=30, timeout_seconds=60),
        GuestShutdownTask(vmid=101, order=20, timeout_seconds=60),
        GuestShutdownTask(vmid=149, order=20, timeout_seconds=60),
        GuestShutdownTask(vmid=700, order=1, timeout_seconds=100),
    )

    assert calculate_guest_shutdown_budget(tasks, max_workers=4) == 280


def test_guest_shutdown_budget_accounts_for_worker_waves_inside_one_group():
    tasks = tuple(
        GuestShutdownTask(vmid=100 + index, order=50, timeout_seconds=30)
        for index in range(5)
    )

    assert calculate_guest_shutdown_budget(tasks, max_workers=2) == 90


def test_missing_startup_order_is_shutdown_before_numbered_groups():
    tasks = (
        GuestShutdownTask(vmid=501, order=None, timeout_seconds=30),
        GuestShutdownTask(vmid=110, order=30, timeout_seconds=60),
        GuestShutdownTask(vmid=700, order=1, timeout_seconds=100),
    )

    assert calculate_guest_shutdown_budget(tasks, max_workers=4) == 190


def test_validation_returns_only_validated_v2_trigger_values_without_budget_facts():
    result = validate_policy(UpsPolicyDraft(20, 180))

    assert result.shutdown_battery_charge_threshold_percent == 20
    assert result.runtime_reserve_seconds == 180
