from app.config import load_config
from app.problems import ProblemState, ProblemTransition
from app.pve_problem_events import (
    PVE_USER_EVENT_TYPES,
    PveProblemEventDebouncer,
    semantic_pve_problem_event,
)


def _state(problem_id: str, *, active: bool, metric: str, value, average=None, threshold=None):
    return ProblemState(
        problem_id=problem_id,
        category="cpu" if problem_id.startswith("cpu_") else "storage",
        severity="warning",
        object_id="cpu" if problem_id.startswith("cpu_") else "local",
        object_name="CPU" if problem_id.startswith("cpu_") else "local",
        metric=metric,
        active=active,
        value=value,
        average=average,
        threshold=threshold,
    )


def test_event_config_defaults_to_30_second_pve_debounce(tmp_path):
    path = tmp_path / "dh_pve_app.conf"
    path.write_text("[mqtt]\nhost = broker\n", encoding="utf-8")
    config = load_config(path)
    assert config.events.pve_problem_debounce_seconds == 30.0


def test_event_config_accepts_explicit_zero_and_custom_delay(tmp_path):
    path = tmp_path / "dh_pve_app.conf"
    path.write_text(
        "[mqtt]\nhost = broker\n[events]\npve_problem_debounce_seconds = 15\n",
        encoding="utf-8",
    )
    assert load_config(path).events.pve_problem_debounce_seconds == 15.0

    path.write_text(
        "[mqtt]\nhost = broker\n[events]\npve_problem_debounce_seconds = 0\n",
        encoding="utf-8",
    )
    assert load_config(path).events.pve_problem_debounce_seconds == 0.0


def test_pve_semantic_event_types_cover_current_problem_catalog():
    assert PVE_USER_EVENT_TYPES == (
        "cpu_temperature_high",
        "cpu_temperature_normal",
        "cpu_throttling_started",
        "cpu_throttling_cleared",
        "storage_usage_high",
        "storage_usage_normal",
        "disk_temperature_high",
        "disk_temperature_normal",
        "gpu_temperature_high",
        "gpu_temperature_normal",
        "fan_control_restore_failed",
        "fan_control_restored",
        "disk_smart_failed",
        "disk_smart_restored",
    )


def test_cpu_throttling_event_contains_assessment_context():
    transition = ProblemTransition(
        "problem_started",
        _state("cpu_throttling", active=False, metric="throttling", value=False),
        _state("cpu_throttling", active=True, metric="throttling", value=True),
    )
    event = semantic_pve_problem_event(
        transition,
        observed_at="2026-09-25T03:30:00+05:00",
        context={
            "temperature_c": 93.0,
            "cpu_frequency_mhz": 1800.0,
            "cpu_usage_percent": 82.5,
        },
    )
    assert event["event_type"] == "cpu_throttling_started"
    assert event["temperature_c"] == 93.0
    assert event["cpu_frequency_mhz"] == 1800.0
    assert event["cpu_usage_percent"] == 82.5


def test_storage_event_contains_usage_capacity_and_threshold():
    transition = ProblemTransition(
        "problem_started",
        _state(
            "storage_local_percent_used",
            active=False,
            metric="percent_used",
            value=79.8,
            average=79.8,
            threshold=80.0,
        ),
        _state(
            "storage_local_percent_used",
            active=True,
            metric="percent_used",
            value=82.3,
            average=81.2,
            threshold=80.0,
        ),
    )
    event = semantic_pve_problem_event(
        transition,
        observed_at="2026-09-25T03:30:00+05:00",
        context={
            "used_gib": 812.4,
            "available_gib": 187.6,
            "total_gib": 1000.0,
        },
    )
    assert event["event_type"] == "storage_usage_high"
    assert event["used_percent"] == 82.3
    assert event["average_used_percent"] == 81.2
    assert event["threshold_percent"] == 80.0
    assert event["available_gib"] == 187.6


def test_debounce_suppresses_short_problem_and_recovery_flap():
    debouncer = PveProblemEventDebouncer(delay_seconds=30.0)
    inactive = _state(
        "cpu_throttling", active=False, metric="throttling", value=False
    )
    active = _state(
        "cpu_throttling", active=True, metric="throttling", value=True
    )

    debouncer.observe(
        ProblemTransition("problem_started", inactive, active),
        now=100.0,
    )
    assert debouncer.due(now=129.9, current_states={"cpu_throttling": active}) == ()

    debouncer.observe(
        ProblemTransition("problem_recovered", active, inactive),
        now=120.0,
    )
    assert debouncer.due(now=200.0, current_states={"cpu_throttling": inactive}) == ()


def test_debounce_emits_start_after_delay_and_debounces_recovery():
    debouncer = PveProblemEventDebouncer(delay_seconds=30.0)
    inactive = _state(
        "cpu_throttling", active=False, metric="throttling", value=False
    )
    active = _state(
        "cpu_throttling", active=True, metric="throttling", value=True
    )

    start = ProblemTransition("problem_started", inactive, active)
    debouncer.observe(start, now=100.0)
    due = debouncer.due(now=130.0, current_states={"cpu_throttling": active})
    assert len(due) == 1
    assert due[0].event_type == "problem_started"
    debouncer.acknowledge(due[0])

    recovery = ProblemTransition("problem_recovered", active, inactive)
    debouncer.observe(recovery, now=140.0)
    assert debouncer.due(now=169.9, current_states={"cpu_throttling": inactive}) == ()
    due = debouncer.due(now=170.0, current_states={"cpu_throttling": inactive})
    assert len(due) == 1
    assert due[0].event_type == "problem_recovered"
