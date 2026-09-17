from __future__ import annotations

from dataclasses import dataclass

from .problems import ProblemAggregate, ProblemState, ProblemTransition
from .ups_health import STATUS_DERIVED_UPS_PROBLEM_IDS, ups_problem_observations
from .ups_nut import UpsSnapshot


_SEVERITY_RANK = {"ok": 0, "info": 1, "warning": 2, "critical": 3}


def _compact(state: ProblemState) -> dict[str, object]:
    return {
        "problem_id": state.problem_id,
        "category": state.category,
        "severity": state.severity,
        "object_id": state.object_id,
        "object_name": state.object_name,
        "metric": state.metric,
        "value": state.value,
        "average": state.average,
        "threshold": state.threshold,
    }


@dataclass
class UpsProblemEngine:
    object_id: str
    object_name: str

    def __post_init__(self) -> None:
        self._states: dict[str, ProblemState] = {}

    def states(self) -> tuple[ProblemState, ...]:
        return tuple(self._states[key] for key in sorted(self._states))

    def _commit(self, state: ProblemState) -> ProblemTransition | None:
        previous = self._states.get(state.problem_id)
        self._states[state.problem_id] = state
        if previous is None:
            if state.active:
                return ProblemTransition("problem_started", None, state)
            return None
        if previous.active != state.active:
            return ProblemTransition(
                "problem_started" if state.active else "problem_recovered",
                previous,
                state,
            )
        return None

    def observe(
        self,
        snapshot: UpsSnapshot | None,
        *,
        nut_available: bool,
    ) -> tuple[ProblemTransition, ...]:
        transitions: list[ProblemTransition] = []
        for observation in ups_problem_observations(
            snapshot,
            nut_available=nut_available,
        ):
            state = ProblemState(
                problem_id=observation.problem_id,
                category="ups",
                severity=observation.severity,
                object_id=self.object_id,
                object_name=self.object_name,
                metric=observation.problem_id,
                active=observation.active,
                value=observation.active,
                average=None,
                threshold=None,
            )
            transition = self._commit(state)
            if (
                transition is not None
                and observation.problem_id not in STATUS_DERIVED_UPS_PROBLEM_IDS
            ):
                transitions.append(transition)
        return tuple(transitions)

    def aggregate(self) -> ProblemAggregate:
        active_states = sorted(
            (state for state in self._states.values() if state.active),
            key=lambda state: state.problem_id,
        )
        count = len(active_states)
        severity = (
            max(
                active_states,
                key=lambda state: _SEVERITY_RANK.get(state.severity, 0),
            ).severity
            if active_states
            else "ok"
        )
        return ProblemAggregate(
            count=count,
            severity=severity,
            active=tuple(_compact(state) for state in active_states),
        )
