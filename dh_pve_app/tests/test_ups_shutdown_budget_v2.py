from app.ups_shutdown_budget import (
    ShutdownBudgetInputs,
    calculate_shutdown_budget,
)


def test_budget_uses_max_of_configured_and_comparable_observed_guest_time():
    result = calculate_shutdown_budget(
        ShutdownBudgetInputs(
            configured_guest_budget_seconds=280,
            observed_guest_budget_seconds=340,
            hostsync_seconds=120,
            hostsync_applicable=True,
            finaldelay_seconds=5,
            observed_host_tail_seconds=70,
            host_tail_fallback_seconds=90,
        )
    )

    assert result.available is True
    assert result.effective_guest_budget_seconds == 340
    assert result.hostsync_budget_seconds == 120
    assert result.host_tail_budget_seconds == 90
    assert result.shutdown_budget_seconds == 555
    assert result.unavailable_reason is None


def test_history_never_reduces_configured_guest_ceiling_or_host_tail_floor():
    result = calculate_shutdown_budget(
        ShutdownBudgetInputs(
            configured_guest_budget_seconds=280,
            observed_guest_budget_seconds=200,
            hostsync_seconds=120,
            hostsync_applicable=True,
            finaldelay_seconds=5,
            observed_host_tail_seconds=30,
            host_tail_fallback_seconds=90,
        )
    )

    assert result.effective_guest_budget_seconds == 280
    assert result.host_tail_budget_seconds == 90
    assert result.shutdown_budget_seconds == 495


def test_hostsync_is_zero_when_no_relevant_secondaries_exist():
    result = calculate_shutdown_budget(
        ShutdownBudgetInputs(
            configured_guest_budget_seconds=280,
            observed_guest_budget_seconds=None,
            hostsync_seconds=None,
            hostsync_applicable=False,
            finaldelay_seconds=5,
            observed_host_tail_seconds=140,
            host_tail_fallback_seconds=90,
        )
    )

    assert result.available is True
    assert result.hostsync_budget_seconds == 0
    assert result.host_tail_budget_seconds == 140
    assert result.shutdown_budget_seconds == 425


def test_missing_optional_history_is_not_an_error():
    result = calculate_shutdown_budget(
        ShutdownBudgetInputs(
            configured_guest_budget_seconds=280,
            observed_guest_budget_seconds=None,
            hostsync_seconds=120,
            hostsync_applicable=True,
            finaldelay_seconds=5,
            observed_host_tail_seconds=None,
            host_tail_fallback_seconds=90,
        )
    )

    assert result.available is True
    assert result.effective_guest_budget_seconds == 280
    assert result.host_tail_budget_seconds == 90
    assert result.shutdown_budget_seconds == 495


def test_missing_mandatory_component_makes_runtime_guard_budget_unavailable():
    cases = (
        ShutdownBudgetInputs(None, None, 120, True, 5, None, 90),
        ShutdownBudgetInputs(280, None, None, True, 5, None, 90),
        ShutdownBudgetInputs(280, None, 120, None, 5, None, 90),
        ShutdownBudgetInputs(280, None, 120, True, None, None, 90),
        ShutdownBudgetInputs(280, None, 120, True, 5, None, None),
    )

    for inputs in cases:
        result = calculate_shutdown_budget(inputs)
        assert result.available is False
        assert result.shutdown_budget_seconds is None
        assert result.unavailable_reason


def test_runtime_guard_threshold_adds_only_active_reserve_to_shutdown_budget():
    result = calculate_shutdown_budget(
        ShutdownBudgetInputs(
            configured_guest_budget_seconds=280,
            observed_guest_budget_seconds=340,
            hostsync_seconds=120,
            hostsync_applicable=True,
            finaldelay_seconds=5,
            observed_host_tail_seconds=70,
            host_tail_fallback_seconds=90,
        )
    )

    assert result.runtime_guard_threshold_seconds(180) == 735


def test_invalid_negative_or_boolean_inputs_fail_closed():
    invalid = (
        ShutdownBudgetInputs(-1, None, 120, True, 5, None, 90),
        ShutdownBudgetInputs(280, -1, 120, True, 5, None, 90),
        ShutdownBudgetInputs(280, None, -1, True, 5, None, 90),
        ShutdownBudgetInputs(280, None, 120, True, -1, None, 90),
        ShutdownBudgetInputs(280, None, 120, True, 5, -1, 90),
        ShutdownBudgetInputs(280, None, 120, True, 5, None, -1),
        ShutdownBudgetInputs(True, None, 120, True, 5, None, 90),
    )

    for inputs in invalid:
        result = calculate_shutdown_budget(inputs)
        assert result.available is False
        assert result.shutdown_budget_seconds is None
        assert result.unavailable_reason == "invalid_budget_input"
