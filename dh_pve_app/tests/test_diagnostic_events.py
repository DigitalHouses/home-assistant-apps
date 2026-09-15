from app.diagnostic_events import DiagnosticEvent
from app.problems import ProblemState, ProblemTransition


def _numeric_transition(event_type="problem_started"):
    current = ProblemState(
        problem_id="cpu_temperature",
        category="cpu",
        severity="warning",
        object_id="cpu",
        object_name="CPU",
        metric="temperature_c",
        active=event_type != "problem_recovered",
        value=95.0,
        average=92.5,
        threshold=90.0,
        summary="CPU temperature high",
        details="Average 92.5 °C; threshold 90 °C",
    )
    previous = None
    if event_type != "problem_started":
        previous = ProblemState(
            problem_id="cpu_temperature",
            category="cpu",
            severity="warning",
            object_id="cpu",
            object_name="CPU",
            metric="temperature_c",
            active=event_type != "problem_recovered",
            value=94.0,
            average=91.0,
            threshold=89.0,
            summary="CPU temperature high",
            details="Average 91 °C; threshold 89 °C",
        )
    return ProblemTransition(event_type, previous, current)


def test_diagnostic_event_serializes_exact_schema_v1_fields():
    payload = DiagnosticEvent.from_transition(
        _numeric_transition(),
        active_problem_count=3,
    ).as_payload()

    assert payload == {
        "schema_version": 1,
        "event_type": "problem_started",
        "category": "cpu",
        "severity": "warning",
        "object_id": "cpu",
        "object_name": "CPU",
        "metric": "temperature_c",
        "value": 95.0,
        "average": 92.5,
        "threshold": 90.0,
        "summary": "CPU temperature high",
        "details": "Average 92.5 °C; threshold 90 °C",
        "active_problem_count": 3,
    }


def test_diagnostic_event_preserves_recovered_and_updated_types():
    recovered = DiagnosticEvent.from_transition(
        _numeric_transition("problem_recovered"),
        active_problem_count=0,
    ).as_payload()
    updated = DiagnosticEvent.from_transition(
        _numeric_transition("problem_updated"),
        active_problem_count=1,
    ).as_payload()

    assert recovered["event_type"] == "problem_recovered"
    assert recovered["active_problem_count"] == 0
    assert updated["event_type"] == "problem_updated"
    assert updated["active_problem_count"] == 1


def test_diagnostic_event_keeps_non_applicable_discrete_numeric_fields_nullable():
    state = ProblemState(
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
        summary="SMART Samsung NVMe problem",
        details="SMART Samsung NVMe: problem active",
    )
    payload = DiagnosticEvent.from_transition(
        ProblemTransition("problem_started", None, state),
        active_problem_count=1,
    ).as_payload()

    assert payload["value"] is False
    assert payload["average"] is None
    assert payload["threshold"] is None
