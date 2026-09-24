from __future__ import annotations

from .problems import ProblemTransition


_PROBLEM_EVENTS = {
    ("nut_unavailable", "problem_started"): "nut_unavailable",
    ("nut_unavailable", "problem_recovered"): "nut_restored",
    ("power_state_unknown", "problem_started"): "power_state_unknown",
    ("power_state_unknown", "problem_recovered"): "power_state_restored",
}


def semantic_ups_problem_event(
    transition: ProblemTransition,
    *,
    observed_at: str,
) -> tuple[str, dict[str, object]] | None:
    event_type = _PROBLEM_EVENTS.get(
        (transition.current.problem_id, transition.event_type)
    )
    if event_type is None:
        return None

    state = transition.current
    payload: dict[str, object] = {
        "schema_version": 2,
        "event_type": event_type,
        "observed_at": observed_at,
        "problem_id": state.problem_id,
        "severity": state.severity,
        "object_id": state.object_id,
        "object_name": state.object_name,
    }
    return f"{event_type}:{observed_at}", payload
