from app.ups_health import (
    STATUS_DERIVED_UPS_PROBLEM_IDS,
    ups_problem_observations,
)
from app.ups_nut import parse_upsc_output
from app.ups_problems import UpsProblemEngine


EXPECTED_PROBLEM_IDS = {
    "nut_unavailable",
    "on_battery",
    "low_battery",
    "overload",
    "replace_battery",
    "bypass",
    "power_state_unknown",
}


def _by_id(snapshot, *, nut_available=True):
    return {
        observation.problem_id: observation
        for observation in ups_problem_observations(
            snapshot,
            nut_available=nut_available,
        )
    }


def test_observations_are_machine_only_and_status_derived_ids_are_explicit():
    observations = ups_problem_observations(parse_upsc_output("ups.status: OL\n"))

    assert {observation.problem_id for observation in observations} == EXPECTED_PROBLEM_IDS
    assert all(
        set(observation.__dict__) == {"problem_id", "active", "severity"}
        for observation in observations
    )
    assert STATUS_DERIVED_UPS_PROBLEM_IDS == frozenset(
        {"on_battery", "low_battery", "overload", "replace_battery", "bypass"}
    )


def test_healthy_online_ups_has_no_active_problems():
    observations = _by_id(parse_upsc_output("ups.status: OL\n"))

    assert all(not observation.active for observation in observations.values())


def test_on_battery_is_warning_and_low_battery_escalates_to_critical():
    snapshot = parse_upsc_output("ups.status: OB LB DISCHRG\n")
    observations = _by_id(snapshot)

    assert observations["on_battery"].active is True
    assert observations["on_battery"].severity == "warning"
    assert observations["low_battery"].active is True
    assert observations["low_battery"].severity == "critical"

    engine = UpsProblemEngine(object_id="ups", object_name="ups")
    transitions = engine.observe(snapshot, nut_available=True)
    aggregate = engine.aggregate()

    assert {transition.current.problem_id for transition in transitions} == {
        "on_battery",
        "low_battery",
    }
    assert aggregate.count == 2
    assert aggregate.severity == "critical"
    assert aggregate.active[0] == {
        "problem_id": "low_battery",
        "category": "ups",
        "severity": "critical",
        "object_id": "ups",
        "object_name": "ups",
        "metric": "low_battery",
        "value": True,
        "average": None,
        "threshold": None,
    }
    assert aggregate.active[1] == {
        "problem_id": "on_battery",
        "category": "ups",
        "severity": "warning",
        "object_id": "ups",
        "object_name": "ups",
        "metric": "on_battery",
        "value": True,
        "average": None,
        "threshold": None,
    }
    assert all(
        not ({"summary", "details", "message", "label"} & item.keys())
        for item in aggregate.active
    )


def test_overload_is_critical_replace_battery_and_bypass_are_warnings():
    overload = _by_id(parse_upsc_output("ups.status: OL OVER\n"))
    replace_battery = _by_id(parse_upsc_output("ups.status: OL RB\n"))
    bypass = _by_id(parse_upsc_output("ups.status: BYPASS\n"))

    assert overload["overload"].active is True
    assert overload["overload"].severity == "critical"
    assert replace_battery["replace_battery"].active is True
    assert replace_battery["replace_battery"].severity == "warning"
    assert bypass["bypass"].active is True
    assert bypass["bypass"].severity == "warning"


def test_charging_and_discharging_are_not_problems_by_themselves():
    charging = _by_id(parse_upsc_output("ups.status: OL CHRG\n"))
    discharging = _by_id(parse_upsc_output("ups.status: OL DISCHRG\n"))

    assert not any(observation.active for observation in charging.values())
    assert not any(observation.active for observation in discharging.values())


def test_unknown_power_state_is_warning():
    observations = _by_id(parse_upsc_output("ups.status: CAL\n"))

    assert observations["power_state_unknown"].active is True
    assert observations["power_state_unknown"].severity == "warning"


def test_nut_read_failure_is_critical_even_without_snapshot():
    observations = ups_problem_observations(None, nut_available=False)

    assert len(observations) == 1
    observation = observations[0]
    assert observation.problem_id == "nut_unavailable"
    assert observation.active is True
    assert observation.severity == "critical"
    assert set(observation.__dict__) == {"problem_id", "active", "severity"}
