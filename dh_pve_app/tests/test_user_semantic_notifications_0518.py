from pathlib import Path

from app.problems import ProblemState, ProblemTransition
from app.ups_status_events import semantic_status_events
from app.ups_event_context import ups_snapshot_event_context
from app.ups_nut import parse_upsc_output
from app.ups_problem_events import semantic_ups_problem_event


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    ROOT / "examples/packages/dh_app_pve_notification_local_package.yaml",
    ROOT / "examples/packages/locales/ru/dh_app_pve_notification_local_package.yaml",
)

UPS_USER_EVENT_TYPES = (
    "nut_unavailable",
    "nut_restored",
    "power_state_unknown",
    "power_state_restored",
    "line_power_lost",
    "line_power_restored",
    "low_battery_started",
    "low_battery_cleared",
    "high_battery_started",
    "high_battery_cleared",
    "replace_battery_started",
    "replace_battery_cleared",
    "bypass_started",
    "bypass_ended",
    "calibration_started",
    "calibration_ended",
    "output_off",
    "output_restored",
    "overload_started",
    "overload_cleared",
    "trim_started",
    "trim_ended",
    "boost_started",
    "boost_ended",
    "forced_shutdown_started",
    "forced_shutdown_cleared",
    "alarm_started",
    "alarm_cleared",
    "battery_discharge_level_crossed",
    "battery_fully_charged",
    "shutdown_committed",
    "config_changed",
)


def _types(previous, current):
    return tuple(
        payload["event_type"]
        for _key, payload in semantic_status_events(
            previous_status=previous,
            current_status=current,
            previous_raw_status=(),
            current_raw_status=(),
            observed_at="2026-09-25T03:00:00+05:00",
            battery_charge_percent=88,
            battery_runtime_seconds=900,
        )
    )


def test_status_transitions_expand_into_user_semantic_events():
    pairs = (
        (("online",), ("on_battery",), ("line_power_lost",)),
        (("on_battery",), ("online",), ("line_power_restored",)),
        (("online",), ("online", "low_battery"), ("low_battery_started",)),
        (("online", "low_battery"), ("online",), ("low_battery_cleared",)),
        (("online",), ("online", "high_battery"), ("high_battery_started",)),
        (("online", "high_battery"), ("online",), ("high_battery_cleared",)),
        (("online",), ("online", "replace_battery"), ("replace_battery_started",)),
        (("online", "replace_battery"), ("online",), ("replace_battery_cleared",)),
        (("online",), ("online", "bypass"), ("bypass_started",)),
        (("online", "bypass"), ("online",), ("bypass_ended",)),
        (("online",), ("online", "calibration"), ("calibration_started",)),
        (("online", "calibration"), ("online",), ("calibration_ended",)),
        (("online",), ("online", "output_off"), ("output_off",)),
        (("online", "output_off"), ("online",), ("output_restored",)),
        (("online",), ("online", "overload"), ("overload_started",)),
        (("online", "overload"), ("online",), ("overload_cleared",)),
        (("online",), ("online", "trim"), ("trim_started",)),
        (("online", "trim"), ("online",), ("trim_ended",)),
        (("online",), ("online", "boost"), ("boost_started",)),
        (("online", "boost"), ("online",), ("boost_ended",)),
        (("online",), ("online", "forced_shutdown"), ("forced_shutdown_started",)),
        (("online", "forced_shutdown"), ("online",), ("forced_shutdown_cleared",)),
        (("online",), ("online", "alarm"), ("alarm_started",)),
        (("online", "alarm"), ("online",), ("alarm_cleared",)),
    )
    for previous, current, expected in pairs:
        assert _types(previous, current) == expected


def _problem(problem_id, active):
    return ProblemState(
        problem_id=problem_id,
        category="ups",
        severity="critical",
        object_id="ups",
        object_name="UPS",
        metric=problem_id,
        active=active,
        value=active,
        average=None,
        threshold=None,
    )


def test_non_status_ups_problems_have_explicit_user_events():
    cases = (
        ("nut_unavailable", "problem_started", "nut_unavailable"),
        ("nut_unavailable", "problem_recovered", "nut_restored"),
        ("power_state_unknown", "problem_started", "power_state_unknown"),
        ("power_state_unknown", "problem_recovered", "power_state_restored"),
    )
    for problem_id, transition_type, expected in cases:
        current = _problem(problem_id, transition_type == "problem_started")
        previous = None if transition_type == "problem_started" else _problem(problem_id, True)
        event = semantic_ups_problem_event(
            ProblemTransition(transition_type, previous, current),
            observed_at="2026-09-25T03:00:00+05:00",
        )
        assert event is not None
        _key, payload = event
        assert payload["event_type"] == expected


def test_local_packages_expose_every_user_event_as_a_named_trigger():
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        for event_type in UPS_USER_EVENT_TYPES:
            assert f"- {event_type}" in text, f"{path}: missing event {event_type}"
            assert f"id: {event_type}" in text, f"{path}: missing trigger id {event_type}"

        assert "id: ups_status_changed" not in text


def test_pve_generic_problem_triggers_are_not_user_facing():
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        assert "id: problem_started" not in text
        assert "id: problem_recovered" not in text
        assert "id: ups_status_changed" not in text


def test_ups_snapshot_context_contains_assessment_measurements():
    snapshot = parse_upsc_output(
        "ups.status: OB DISCHRG\n"
        "battery.charge: 96\n"
        "battery.runtime: 3720\n"
        "ups.load: 8\n"
        "ups.realpower.nominal: 1320\n"
        "input.voltage: 199\n"
        "output.voltage: 220\n"
        "input.frequency: 49.9\n"
        "output.frequency: 50.0\n"
        "input.transfer.low: 200\n"
    )
    context = ups_snapshot_event_context(snapshot)

    assert context["battery_charge_percent"] == 96.0
    assert context["battery_runtime_seconds"] == 3720.0
    assert context["load_percent"] == 8.0
    assert context["nominal_real_power_w"] == 1320.0
    assert context["input_voltage_v"] == 199.0
    assert context["output_voltage_v"] == 220.0
    assert context["input_transfer_low_v"] == 200.0


def test_semantic_status_event_carries_event_time_assessment_context():
    events = semantic_status_events(
        previous_status=("online",),
        current_status=("on_battery",),
        previous_raw_status=("OL",),
        current_raw_status=("OB",),
        observed_at="2026-09-25T03:00:00+05:00",
        battery_charge_percent=96.0,
        battery_runtime_seconds=3720.0,
        context={
            "load_percent": 8.0,
            "input_voltage_v": 199.0,
            "output_voltage_v": 220.0,
        },
    )
    assert len(events) == 1
    payload = events[0][1]
    assert payload["event_type"] == "line_power_lost"
    assert payload["battery_charge_percent"] == 96.0
    assert payload["battery_runtime_seconds"] == 3720.0
    assert payload["load_percent"] == 8.0
    assert payload["input_voltage_v"] == 199.0
    assert payload["output_voltage_v"] == 220.0
