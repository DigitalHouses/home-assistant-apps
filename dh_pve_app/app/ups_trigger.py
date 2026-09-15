from __future__ import annotations

import math
from dataclasses import dataclass

from .ups_nut import UpsSnapshot
from .ups_policy import UpsPolicyDraft
from .ups_shutdown_budget import ShutdownBudgetResult


@dataclass(frozen=True)
class SoftwareShutdownTriggerResult:
    triggered: bool
    reason: str | None
    charge_guard_satisfied: bool
    runtime_guard_satisfied: bool
    charge_percent: float | None
    runtime_seconds: float | None
    charge_threshold_percent: int
    runtime_guard_threshold_seconds: int | None


def _valid_charge(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0 or numeric > 100:
        return None
    return numeric


def _valid_runtime(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        return None
    return numeric


def evaluate_software_shutdown_trigger(
    snapshot: UpsSnapshot,
    policy: UpsPolicyDraft,
    budget: ShutdownBudgetResult,
) -> SoftwareShutdownTriggerResult:
    charge = _valid_charge(snapshot.battery_charge_percent)
    runtime = _valid_runtime(snapshot.runtime_seconds)
    runtime_threshold = budget.runtime_guard_threshold_seconds(
        policy.runtime_reserve_seconds
    )

    if not snapshot.on_battery:
        return SoftwareShutdownTriggerResult(
            triggered=False,
            reason=None,
            charge_guard_satisfied=False,
            runtime_guard_satisfied=False,
            charge_percent=charge,
            runtime_seconds=runtime,
            charge_threshold_percent=policy.shutdown_battery_charge_threshold_percent,
            runtime_guard_threshold_seconds=runtime_threshold,
        )

    charge_guard = (
        charge is not None
        and charge <= policy.shutdown_battery_charge_threshold_percent
    )
    runtime_guard = (
        runtime is not None
        and runtime_threshold is not None
        and runtime <= runtime_threshold
    )

    # Both predicates may become true in the same NUT sample. Charge guard has
    # stable reporting precedence only; both satisfied flags remain visible.
    reason = "charge_guard" if charge_guard else "runtime_guard" if runtime_guard else None

    return SoftwareShutdownTriggerResult(
        triggered=reason is not None,
        reason=reason,
        charge_guard_satisfied=charge_guard,
        runtime_guard_satisfied=runtime_guard,
        charge_percent=charge,
        runtime_seconds=runtime,
        charge_threshold_percent=policy.shutdown_battery_charge_threshold_percent,
        runtime_guard_threshold_seconds=runtime_threshold,
    )
