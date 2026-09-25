from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShutdownBudgetInputs:
    configured_guest_budget_seconds: int | None
    observed_guest_budget_seconds: int | None
    hostsync_seconds: int | None
    hostsync_applicable: bool | None
    finaldelay_seconds: int | None
    observed_host_tail_seconds: int | None
    host_tail_fallback_seconds: int | None


@dataclass(frozen=True)
class ShutdownBudgetResult:
    available: bool
    configured_guest_budget_seconds: int | None
    observed_guest_budget_seconds: int | None
    effective_guest_budget_seconds: int | None
    hostsync_budget_seconds: int | None
    finaldelay_seconds: int | None
    observed_host_tail_seconds: int | None
    host_tail_fallback_seconds: int | None
    host_tail_budget_seconds: int | None
    shutdown_budget_seconds: int | None
    unavailable_reason: str | None
    configuration_fingerprint: str | None = None
    history_evidence_status: str = "none"
    all_configured_guest_budget_seconds: int | None = None
    running_guests: tuple[str, ...] = ()
    shutdown_sequence: tuple[tuple[str, ...], ...] = ()

    def runtime_guard_threshold_seconds(self, runtime_reserve_seconds: int) -> int | None:
        if self.shutdown_budget_seconds is None:
            return None
        if not _valid_seconds(runtime_reserve_seconds):
            return None
        return self.shutdown_budget_seconds + runtime_reserve_seconds


def _valid_seconds(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_optional_seconds(value: object) -> bool:
    return value is None or _valid_seconds(value)


def _unavailable(
    inputs: ShutdownBudgetInputs,
    reason: str,
) -> ShutdownBudgetResult:
    return ShutdownBudgetResult(
        available=False,
        configured_guest_budget_seconds=inputs.configured_guest_budget_seconds,
        observed_guest_budget_seconds=inputs.observed_guest_budget_seconds,
        effective_guest_budget_seconds=None,
        hostsync_budget_seconds=None,
        finaldelay_seconds=inputs.finaldelay_seconds,
        observed_host_tail_seconds=inputs.observed_host_tail_seconds,
        host_tail_fallback_seconds=inputs.host_tail_fallback_seconds,
        host_tail_budget_seconds=None,
        shutdown_budget_seconds=None,
        unavailable_reason=reason,
    )


def calculate_shutdown_budget(inputs: ShutdownBudgetInputs) -> ShutdownBudgetResult:
    numeric_values = (
        inputs.configured_guest_budget_seconds,
        inputs.observed_guest_budget_seconds,
        inputs.hostsync_seconds,
        inputs.finaldelay_seconds,
        inputs.observed_host_tail_seconds,
        inputs.host_tail_fallback_seconds,
    )
    if not all(_valid_optional_seconds(value) for value in numeric_values):
        return _unavailable(inputs, "invalid_budget_input")
    if inputs.hostsync_applicable is not None and not isinstance(
        inputs.hostsync_applicable, bool
    ):
        return _unavailable(inputs, "invalid_budget_input")

    if inputs.configured_guest_budget_seconds is None:
        return _unavailable(inputs, "configured_guest_budget_unavailable")
    if inputs.hostsync_applicable is None:
        return _unavailable(inputs, "hostsync_applicability_unavailable")
    if inputs.hostsync_applicable and inputs.hostsync_seconds is None:
        return _unavailable(inputs, "hostsync_unavailable")
    if inputs.finaldelay_seconds is None:
        return _unavailable(inputs, "finaldelay_unavailable")
    if inputs.host_tail_fallback_seconds is None:
        return _unavailable(inputs, "host_tail_fallback_unavailable")

    effective_guest_budget = inputs.configured_guest_budget_seconds
    if inputs.observed_guest_budget_seconds is not None:
        effective_guest_budget = max(
            effective_guest_budget,
            inputs.observed_guest_budget_seconds,
        )

    hostsync_budget = inputs.hostsync_seconds if inputs.hostsync_applicable else 0
    assert hostsync_budget is not None

    host_tail_budget = inputs.host_tail_fallback_seconds
    if inputs.observed_host_tail_seconds is not None:
        host_tail_budget = max(host_tail_budget, inputs.observed_host_tail_seconds)

    shutdown_budget = (
        effective_guest_budget
        + hostsync_budget
        + inputs.finaldelay_seconds
        + host_tail_budget
    )

    return ShutdownBudgetResult(
        available=True,
        configured_guest_budget_seconds=inputs.configured_guest_budget_seconds,
        observed_guest_budget_seconds=inputs.observed_guest_budget_seconds,
        effective_guest_budget_seconds=effective_guest_budget,
        hostsync_budget_seconds=hostsync_budget,
        finaldelay_seconds=inputs.finaldelay_seconds,
        observed_host_tail_seconds=inputs.observed_host_tail_seconds,
        host_tail_fallback_seconds=inputs.host_tail_fallback_seconds,
        host_tail_budget_seconds=host_tail_budget,
        shutdown_budget_seconds=shutdown_budget,
        unavailable_reason=None,
    )
