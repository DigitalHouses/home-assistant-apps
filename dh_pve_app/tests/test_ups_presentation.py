from app.presentation import PublicationProfile
from app.presentation_ups import UpsPresentationRouter


def payload(**overrides):
    base = {
        "available": True,
        "collected_at": "2026-09-14T20:00:00+05:00",
        "last_refresh": None,
        "status": "Online",
        "error": None,
        "status_raw": "OL",
        "status_tokens": ["OL"],
        "line_power": True,
        "on_battery": False,
        "low_battery": False,
        "replace_battery": False,
        "overload": False,
        "bypass": False,
        "charging": False,
        "discharging": False,
        "battery_charge_percent": 100.0,
        "battery_runtime_minutes": 36.0,
        "runtime_seconds": 2160.0,
        "battery_voltage_v": 27.0,
        "load_percent": 5.0,
        "input_voltage_v": 220.0,
        "output_voltage_v": 220.0,
        "input_frequency_hz": 50.0,
        "output_frequency_hz": 50.0,
        "manufacturer": "CPS",
        "model": "UT2200E",
        "serial": "ABC",
        "battery_nominal_voltage_v": 24.0,
        "nominal_real_power_w": 1320.0,
        "warning_charge_percent": 20.0,
        "low_charge_percent": 10.0,
        "low_runtime_seconds": 300.0,
        "test_result": "No test initiated",
        "beeper_status": "enabled",
        "problems_count": 0,
        "problems_severity": "ok",
        "problems": [],
        "problems_details": "",
        "capabilities": {"available": True, "count": 2, "commands": ["test.battery.start.quick"]},
        "shutdown_policy": {"state": "Enabled", "guest_shutdown_budget_seconds": 240},
        "policy": {"status": "Active"},
        "test_schedule": {"current_state": "Idle"},
        "test_history": [],
        "shutdown_readiness": {"status": "Ready", "issues": []},
    }
    base.update(overrides)
    return base


def by_group(publications):
    return {item.group: item for item in publications}


def test_startup_partitions_ups_state_into_independent_groups():
    router = UpsPresentationRouter(source_interval_seconds=10.0)

    publications = router.route(payload(), now=0.0, force=True)
    groups = by_group(publications)

    assert set(groups) == {"telemetry", "status", "config", "tests", "diagnostics"}
    assert "battery_charge_percent" in groups["telemetry"].payload
    assert "status" not in groups["telemetry"].payload
    assert groups["status"].payload["status"] == "Online"
    assert "battery_charge_percent" not in groups["status"].payload
    assert groups["config"].payload["model"] == "UT2200E"
    assert groups["tests"].payload["test_result"] == "No test initiated"
    assert groups["diagnostics"].payload["shutdown_readiness"]["status"] == "Ready"


def test_on_battery_transition_publishes_status_immediately_and_enters_detail():
    router = UpsPresentationRouter(source_interval_seconds=10.0)
    router.route(payload(), now=0.0, force=True)

    changed = payload(
        status="On battery",
        status_raw="OB DISCHRG",
        status_tokens=["OB", "DISCHRG"],
        line_power=False,
        on_battery=True,
        discharging=True,
        battery_charge_percent=99.0,
    )
    publications = by_group(router.route(changed, now=10.0))

    assert set(publications) == {"status", "telemetry"}
    assert publications["status"].reason == "change"
    assert publications["telemetry"].reason == "profile_transition"
    assert publications["telemetry"].profile is PublicationProfile.DETAIL


def test_low_battery_transition_is_immediate_detail():
    router = UpsPresentationRouter(source_interval_seconds=10.0)
    router.route(payload(), now=0.0, force=True)

    changed = payload(
        status="Low battery",
        status_raw="OB LB DISCHRG",
        status_tokens=["OB", "LB", "DISCHRG"],
        line_power=False,
        on_battery=True,
        low_battery=True,
        discharging=True,
        battery_charge_percent=8.0,
    )
    publications = by_group(router.route(changed, now=10.0))

    assert publications["telemetry"].profile is PublicationProfile.DETAIL
    assert publications["status"].payload["low_battery"] is True


def test_online_numeric_jitter_waits_for_normal_fifteen_minute_average_window():
    router = UpsPresentationRouter(source_interval_seconds=10.0)
    router.route(payload(load_percent=5.0), now=0.0, force=True)

    assert router.route(payload(load_percent=7.0), now=300.0) == ()
    assert router.route(payload(load_percent=9.0), now=600.0) == ()

    publications = by_group(router.route(payload(load_percent=11.0), now=900.0))
    assert set(publications) == {"telemetry"}
    assert publications["telemetry"].reason == "average_window_complete"
    assert publications["telemetry"].payload["load_percent"] == 9.0


def test_manual_refresh_publishes_all_groups_without_resetting_profile():
    router = UpsPresentationRouter(source_interval_seconds=10.0)
    router.route(payload(), now=0.0, force=True)

    publications = by_group(
        router.route(
            payload(load_percent=17.0, last_refresh="2026-09-14T20:00:10+05:00"),
            now=10.0,
            manual=True,
        )
    )

    assert set(publications) == {"telemetry", "status", "config", "tests", "diagnostics"}
    assert all(item.reason == "manual_refresh" for item in publications.values())
    assert publications["telemetry"].payload["load_percent"] == 17.0


def test_profile_summary_is_ups_only_and_reports_detail_reason():
    router = UpsPresentationRouter(source_interval_seconds=10.0)
    router.route(payload(), now=0.0, force=True)
    router.route(payload(overload=True, status="Overload"), now=10.0)

    assert router.profile_summary() == {
        "profile": "detail",
        "reason": "overload",
    }
