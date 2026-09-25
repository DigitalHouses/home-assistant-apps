import pytest

from app.diagnostic_events import DiagnosticEvent
from app.problems import ProblemState, ProblemTransition


OBSERVED_AT = "2026-09-17T06:00:00+05:00"


def _state(
    *,
    active: bool,
    value: object,
    average: float | None,
    threshold: float | None,
) -> ProblemState:
    return ProblemState(
        problem_id="cpu_temperature",
        category="cpu",
        severity="warning",
        object_id="cpu",
        object_name="CPU",
        metric="temperature_c",
        active=active,
        value=value,
        average=average,
        threshold=threshold,
    )


def _numeric_transition(event_type="problem_started"):
    if event_type == "problem_started":
        previous = _state(active=False, value=76.0, average=75.4, threshold=80.0)
        current = _state(active=True, value=84.0, average=81.2, threshold=80.0)
    elif event_type == "problem_recovered":
        previous = _state(active=True, value=84.0, average=81.2, threshold=80.0)
        current = _state(active=False, value=76.0, average=77.0, threshold=80.0)
    else:
        previous = _state(active=True, value=84.0, average=81.2, threshold=80.0)
        current = _state(active=True, value=86.0, average=82.0, threshold=81.0)
    return ProblemTransition(event_type, previous, current)


def test_diagnostic_event_serializes_exact_schema_v2_fields():
    payload = DiagnosticEvent.from_transition(
        _numeric_transition(),
        active_problem_count=1,
        observed_at=OBSERVED_AT,
    ).as_payload()

    assert payload == {
        "schema_version": 2,
        "event_type": "problem_started",
        "observed_at": OBSERVED_AT,
        "problem_id": "cpu_temperature",
        "category": "cpu",
        "severity": "warning",
        "object_id": "cpu",
        "object_name": "CPU",
        "metric": "temperature_c",
        "previous": {
            "active": False,
            "value": 76.0,
            "average": 75.4,
            "threshold": 80.0,
        },
        "current": {
            "active": True,
            "value": 84.0,
            "average": 81.2,
            "threshold": 80.0,
        },
        "active_problem_count": 1,
    }
    assert not ({"title", "message", "summary", "details", "status_ru"} & payload.keys())


def test_diagnostic_event_preserves_recovered_and_updated_types():
    recovered = DiagnosticEvent.from_transition(
        _numeric_transition("problem_recovered"),
        active_problem_count=0,
        observed_at=OBSERVED_AT,
    ).as_payload()
    updated = DiagnosticEvent.from_transition(
        _numeric_transition("problem_updated"),
        active_problem_count=1,
        observed_at=OBSERVED_AT,
    ).as_payload()

    assert recovered["event_type"] == "problem_recovered"
    assert recovered["previous"]["active"] is True
    assert recovered["current"]["active"] is False
    assert recovered["active_problem_count"] == 0
    assert updated["event_type"] == "problem_updated"
    assert updated["previous"]["threshold"] == 80.0
    assert updated["current"]["threshold"] == 81.0
    assert updated["active_problem_count"] == 1


def test_diagnostic_event_keeps_non_applicable_discrete_numeric_fields_nullable():
    previous = ProblemState(
        problem_id="disk_nvme0_smart",
        category="disk",
        severity="critical",
        object_id="nvme0",
        object_name="Samsung NVMe",
        metric="smart_passed",
        active=False,
        value=True,
        average=None,
        threshold=None,
    )
    current = ProblemState(
        problem_id="disk_nvme0_smart",
        category="disk",
        severity="critical",
        object_id="nvme0",
        object_name="Samsung NVMe",
        metric="smart_passed",
        active=True,
        value=False,
        average=None,
        threshold=None,
    )
    payload = DiagnosticEvent.from_transition(
        ProblemTransition("problem_started", previous, current),
        active_problem_count=1,
        observed_at=OBSERVED_AT,
    ).as_payload()

    assert payload["previous"] == {
        "active": False,
        "value": True,
        "average": None,
        "threshold": None,
    }
    assert payload["current"] == {
        "active": True,
        "value": False,
        "average": None,
        "threshold": None,
    }


def test_diagnostic_event_rejects_timezone_naive_observed_at():
    with pytest.raises(ValueError, match="timezone-aware"):
        DiagnosticEvent.from_transition(
            _numeric_transition(),
            active_problem_count=1,
            observed_at="2026-09-17T06:00:00",
        )
