import pytest

from app.ups_policy import (
    GuestShutdownTask,
    PolicySafetyFacts,
    PolicyValidationError,
    UpsPolicyDraft,
    calculate_guest_shutdown_budget,
    parse_policy_value,
    policy_hash,
    validate_policy,
)


def test_parse_policy_values_accepts_only_user_facing_ranges_and_steps():
    assert parse_policy_value("on_battery_delay_minutes", "30") == 30
    assert parse_policy_value("power_restore_delay_seconds", "120") == 120

    for key, value in (
        ("on_battery_delay_minutes", "4"),
        ("on_battery_delay_minutes", "31"),
        ("on_battery_delay_minutes", "65"),
        ("power_restore_delay_seconds", "30"),
        ("power_restore_delay_seconds", "125"),
        ("power_restore_delay_seconds", "330"),
        ("power_restore_delay_seconds", "abc"),
    ):
        with pytest.raises(PolicyValidationError):
            parse_policy_value(key, value)

    with pytest.raises(PolicyValidationError):
        parse_policy_value("emergency_runtime_reserve_minutes", "15")
    with pytest.raises(PolicyValidationError):
        parse_policy_value("unknown", "10")


def test_policy_hash_is_stable_and_depends_only_on_policy_values():
    first = UpsPolicyDraft(
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
    )
    same = UpsPolicyDraft(
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
    )
    changed = UpsPolicyDraft(
        on_battery_delay_minutes=35,
        power_restore_delay_seconds=120,
    )

    assert policy_hash(first) == policy_hash(same)
    assert len(policy_hash(first)) == 64
    assert policy_hash(first) != policy_hash(changed)


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


def test_validation_returns_only_wait_and_restore_delay():
    facts = PolicySafetyFacts(
        guest_shutdown_budget_seconds=280,
        hostsync_seconds=120,
        finaldelay_seconds=5,
        host_shutdown_reserve_seconds=60,
        ups_poweroff_delay_seconds=60,
        safety_margin_seconds=60,
    )
    draft = UpsPolicyDraft(
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
    )

    result = validate_policy(draft, facts)

    assert result.on_battery_delay_seconds == 1800
    assert result.power_restore_delay_seconds == 120
    assert not hasattr(result, "emergency_runtime_reserve_seconds")
    assert not hasattr(result, "minimum_emergency_runtime_reserve_seconds")
    assert not hasattr(result, "recommended_emergency_runtime_reserve_seconds")


def test_validation_rejects_invalid_host_fact_but_does_not_derive_battery_reserve():
    facts = PolicySafetyFacts(
        guest_shutdown_budget_seconds=-1,
        hostsync_seconds=120,
        finaldelay_seconds=5,
    )
    draft = UpsPolicyDraft(
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
    )

    with pytest.raises(PolicyValidationError, match="guest_shutdown_budget_seconds"):
        validate_policy(draft, facts)
