from app.ups_nut import parse_upsc_output
from app.ups_policy import UpsPolicyDraft
from app.ups_shutdown_budget import ShutdownBudgetInputs, calculate_shutdown_budget
from app.ups_trigger import (
    SoftwareShutdownController,
    evaluate_software_shutdown_trigger,
)


def _budget(seconds_case: str = "available"):
    if seconds_case == "unavailable":
        return calculate_shutdown_budget(
            ShutdownBudgetInputs(None, None, 120, True, 5, None, 90)
        )
    return calculate_shutdown_budget(
        ShutdownBudgetInputs(280, None, 120, True, 5, None, 90)
    )


def _snapshot(status: str, charge: object, runtime: object):
    lines = [f"ups.status: {status}"]
    if charge is not None:
        lines.append(f"battery.charge: {charge}")
    if runtime is not None:
        lines.append(f"battery.runtime: {runtime}")
    return parse_upsc_output("\n".join(lines) + "\n")


def test_trigger_a_commits_on_first_valid_sample_at_or_below_charge_threshold():
    policy = UpsPolicyDraft(20, 180)

    at_threshold = evaluate_software_shutdown_trigger(
        _snapshot("OB", 20, 9999), policy, _budget()
    )
    below_threshold = evaluate_software_shutdown_trigger(
        _snapshot("OB", 19, 9999), policy, _budget()
    )

    assert at_threshold.triggered is True
    assert at_threshold.reason == "charge_guard"
    assert at_threshold.charge_guard_satisfied is True
    assert below_threshold.triggered is True
    assert below_threshold.reason == "charge_guard"


def test_trigger_b_uses_shutdown_budget_plus_active_runtime_reserve():
    policy = UpsPolicyDraft(20, 180)
    budget = _budget()
    assert budget.shutdown_budget_seconds == 495

    at_threshold = evaluate_software_shutdown_trigger(
        _snapshot("OB", 80, 675), policy, budget
    )
    above_threshold = evaluate_software_shutdown_trigger(
        _snapshot("OB", 80, 676), policy, budget
    )

    assert at_threshold.triggered is True
    assert at_threshold.reason == "runtime_guard"
    assert at_threshold.runtime_guard_threshold_seconds == 675
    assert above_threshold.triggered is False
    assert above_threshold.reason is None


def test_software_guards_require_on_battery_even_when_values_are_low():
    result = evaluate_software_shutdown_trigger(
        _snapshot("OL", 5, 30), UpsPolicyDraft(20, 180), _budget()
    )

    assert result.triggered is False
    assert result.charge_guard_satisfied is False
    assert result.runtime_guard_satisfied is False


def test_missing_or_invalid_telemetry_is_omitted_never_treated_as_zero():
    policy = UpsPolicyDraft(20, 180)
    cases = (
        _snapshot("OB", None, None),
        _snapshot("OB", "nan", "nan"),
        _snapshot("OB", "inf", "inf"),
        _snapshot("OB", -1, -1),
        _snapshot("OB", 101, 9999),
    )

    for snapshot in cases:
        result = evaluate_software_shutdown_trigger(snapshot, policy, _budget())
        assert result.triggered is False
        assert result.charge_guard_satisfied is False
        assert result.runtime_guard_satisfied is False


def test_unavailable_budget_disables_only_runtime_guard():
    policy = UpsPolicyDraft(20, 180)

    runtime_only = evaluate_software_shutdown_trigger(
        _snapshot("OB", 80, 1), policy, _budget("unavailable")
    )
    charge = evaluate_software_shutdown_trigger(
        _snapshot("OB", 20, 1), policy, _budget("unavailable")
    )

    assert runtime_only.triggered is False
    assert runtime_only.runtime_guard_threshold_seconds is None
    assert charge.triggered is True
    assert charge.reason == "charge_guard"


def test_native_low_battery_token_is_not_reimplemented_as_software_trigger():
    result = evaluate_software_shutdown_trigger(
        _snapshot("OB LB", 80, 9999), UpsPolicyDraft(20, 180), _budget()
    )

    assert result.triggered is False
    assert result.reason is None


def test_simultaneous_software_guards_report_both_and_use_stable_reason_order():
    result = evaluate_software_shutdown_trigger(
        _snapshot("OB", 10, 1), UpsPolicyDraft(20, 180), _budget()
    )

    assert result.triggered is True
    assert result.charge_guard_satisfied is True
    assert result.runtime_guard_satisfied is True
    assert result.reason == "charge_guard"


def test_controller_executes_only_once_after_successful_commitment():
    calls = []
    controller = SoftwareShutdownController(lambda reason: calls.append(reason))
    snapshot = _snapshot("OB", 20, 9999)
    policy = UpsPolicyDraft(20, 180)

    first = controller.evaluate_and_commit(snapshot, policy, _budget())
    second = controller.evaluate_and_commit(snapshot, policy, _budget())

    assert first is not None and first.triggered is True
    assert second is not None and second.triggered is True
    assert calls == ["charge_guard"]
    assert controller.committed is True
    assert controller.committed_reason == "charge_guard"


def test_controller_does_not_latch_failed_executor_and_retries_next_sample():
    calls = []

    def executor(reason):
        calls.append(reason)
        if len(calls) == 1:
            raise RuntimeError("executor failed")

    controller = SoftwareShutdownController(executor)
    snapshot = _snapshot("OB", 80, 1)
    policy = UpsPolicyDraft(20, 180)

    try:
        controller.evaluate_and_commit(snapshot, policy, _budget())
    except RuntimeError:
        pass
    else:
        raise AssertionError("executor failure must propagate")

    assert controller.committed is False
    controller.evaluate_and_commit(snapshot, policy, _budget())
    assert calls == ["runtime_guard", "runtime_guard"]
    assert controller.committed is True
    assert controller.committed_reason == "runtime_guard"


def test_controller_without_active_policy_never_executes():
    calls = []
    controller = SoftwareShutdownController(lambda reason: calls.append(reason))

    result = controller.evaluate_and_commit(_snapshot("OB", 1, 1), None, _budget())

    assert result is None
    assert calls == []
    assert controller.committed is False
