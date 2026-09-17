from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .problems import ProblemState, ProblemTransition


SCHEMA_VERSION = 2
EVENT_TYPES = frozenset(
    {
        "problem_started",
        "problem_recovered",
        "problem_updated",
    }
)


def _transition_state(state: ProblemState | None) -> dict[str, object] | None:
    if state is None:
        return None
    return {
        "active": state.active,
        "value": state.value,
        "average": state.average,
        "threshold": state.threshold,
    }


def _validate_observed_at(observed_at: str) -> str:
    if not isinstance(observed_at, str) or not observed_at:
        raise ValueError("observed_at must be a timezone-aware ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(observed_at)
    except ValueError as exc:
        raise ValueError("observed_at must be a timezone-aware ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    return observed_at


@dataclass(frozen=True)
class DiagnosticEvent:
    schema_version: int
    event_type: str
    observed_at: str
    problem_id: str
    category: str
    severity: str
    object_id: str
    object_name: str
    metric: str
    previous: dict[str, object] | None
    current: dict[str, object]
    active_problem_count: int

    @classmethod
    def from_transition(
        cls,
        transition: ProblemTransition,
        *,
        active_problem_count: int,
        observed_at: str,
    ) -> "DiagnosticEvent":
        if transition.event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported diagnostic event type: {transition.event_type}")
        if (
            isinstance(active_problem_count, bool)
            or not isinstance(active_problem_count, int)
            or active_problem_count < 0
        ):
            raise ValueError("active_problem_count must be a non-negative integer")

        current = transition.current
        return cls(
            schema_version=SCHEMA_VERSION,
            event_type=transition.event_type,
            observed_at=_validate_observed_at(observed_at),
            problem_id=current.problem_id,
            category=current.category,
            severity=current.severity,
            object_id=current.object_id,
            object_name=current.object_name,
            metric=current.metric,
            previous=_transition_state(transition.previous),
            current=_transition_state(current),
            active_problem_count=active_problem_count,
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_type": self.event_type,
            "observed_at": self.observed_at,
            "problem_id": self.problem_id,
            "category": self.category,
            "severity": self.severity,
            "object_id": self.object_id,
            "object_name": self.object_name,
            "metric": self.metric,
            "previous": self.previous,
            "current": self.current,
            "active_problem_count": self.active_problem_count,
        }
