from __future__ import annotations

from dataclasses import dataclass

from .ups_nut import UpsSnapshot


STATUS_DERIVED_UPS_PROBLEM_IDS = frozenset(
    {"on_battery", "low_battery", "overload", "replace_battery", "bypass"}
)


@dataclass(frozen=True)
class UpsProblemSummary:
    count: int
    severity: str


@dataclass(frozen=True)
class UpsProblemObservation:
    problem_id: str
    active: bool
    severity: str


def ups_problem_observations(
    snapshot: UpsSnapshot | None,
    *,
    nut_available: bool = True,
) -> tuple[UpsProblemObservation, ...]:
    """Return decision-ready UPS problem states with machine-only semantics.

    When NUT is unavailable, snapshot-derived problem states are deliberately
    omitted rather than forced OFF. This lets callers preserve the last known
    retained state until authoritative UPS data becomes available again.
    """
    if not nut_available or snapshot is None:
        return (
            UpsProblemObservation(
                problem_id="nut_unavailable",
                active=True,
                severity="critical",
            ),
        )

    power_state_known = snapshot.line_power or snapshot.on_battery or snapshot.bypass
    return (
        UpsProblemObservation(
            problem_id="nut_unavailable",
            active=False,
            severity="critical",
        ),
        UpsProblemObservation(
            problem_id="on_battery",
            active=snapshot.on_battery,
            severity="warning",
        ),
        UpsProblemObservation(
            problem_id="low_battery",
            active=snapshot.low_battery,
            severity="critical",
        ),
        UpsProblemObservation(
            problem_id="overload",
            active=snapshot.overload,
            severity="critical",
        ),
        UpsProblemObservation(
            problem_id="replace_battery",
            active=snapshot.replace_battery,
            severity="warning",
        ),
        UpsProblemObservation(
            problem_id="bypass",
            active=snapshot.bypass,
            severity="warning",
        ),
        UpsProblemObservation(
            problem_id="power_state_unknown",
            active=not power_state_known,
            severity="warning",
        ),
    )


def summarize_ups_problems(
    snapshot: UpsSnapshot | None,
    *,
    nut_available: bool = True,
) -> UpsProblemSummary:
    active = tuple(
        observation
        for observation in ups_problem_observations(
            snapshot,
            nut_available=nut_available,
        )
        if observation.active
    )
    severities = tuple(observation.severity for observation in active)

    if "critical" in severities:
        severity = "critical"
    elif "warning" in severities:
        severity = "warning"
    else:
        severity = "ok"

    return UpsProblemSummary(
        count=len(active),
        severity=severity,
    )
