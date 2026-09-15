from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .problems import ProblemTransition


SCHEMA_VERSION = 1
EVENT_TYPES = frozenset(
    {
        "problem_started",
        "problem_recovered",
        "problem_updated",
    }
)


@dataclass(frozen=True)
class DiagnosticEvent:
    schema_version: int
    event_type: str
    category: str
    severity: str
    object_id: str
    object_name: str
    metric: str
    value: object | None
    average: float | None
    threshold: float | None
    summary: str
    details: str
    active_problem_count: int

    @classmethod
    def from_transition(
        cls,
        transition: ProblemTransition,
        *,
        active_problem_count: int,
    ) -> "DiagnosticEvent":
        if transition.event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported diagnostic event type: {transition.event_type}")
        if isinstance(active_problem_count, bool) or active_problem_count < 0:
            raise ValueError("active_problem_count must be a non-negative integer")

        current = transition.current
        return cls(
            schema_version=SCHEMA_VERSION,
            event_type=transition.event_type,
            category=current.category,
            severity=current.severity,
            object_id=current.object_id,
            object_name=current.object_name,
            metric=current.metric,
            value=current.value,
            average=current.average,
            threshold=current.threshold,
            summary=current.summary,
            details=current.details,
            active_problem_count=int(active_problem_count),
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_type": self.event_type,
            "category": self.category,
            "severity": self.severity,
            "object_id": self.object_id,
            "object_name": self.object_name,
            "metric": self.metric,
            "value": self.value,
            "average": self.average,
            "threshold": self.threshold,
            "summary": self.summary,
            "details": self.details,
            "active_problem_count": self.active_problem_count,
        }
