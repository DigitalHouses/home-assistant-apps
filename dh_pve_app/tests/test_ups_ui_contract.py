from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "examples" / "dh_app_pve_ups_dashboard.yaml"


def _text() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def test_ups_dashboard_uses_canonical_status_and_telemetry():
    assert DASHBOARD.is_file()
    text = _text()

    for entity_id in (
        "sensor.dh_app_pve_ups_problems",
        "sensor.dh_app_pve_ups_status",
        "sensor.dh_app_pve_ups_battery_charge",
        "sensor.dh_app_pve_ups_battery_runtime_minutes",
        "sensor.dh_app_pve_ups_load",
        "sensor.dh_app_pve_ups_input_voltage",
        "sensor.dh_app_pve_ups_output_voltage",
        "button.dh_app_pve_ups_refresh",
    ):
        assert entity_id in text


def test_ups_dashboard_uses_app_owned_problem_state():
    text = _text()

    for entity_id in (
        "binary_sensor.dh_app_pve_ups_nut_unavailable_problem",
        "binary_sensor.dh_app_pve_ups_on_battery_problem",
        "binary_sensor.dh_app_pve_ups_low_battery_problem",
        "binary_sensor.dh_app_pve_ups_overload_problem",
        "binary_sensor.dh_app_pve_ups_replace_battery_problem",
        "binary_sensor.dh_app_pve_ups_bypass_problem",
        "binary_sensor.dh_app_pve_ups_power_state_unknown_problem",
    ):
        assert entity_id in text

    assert "states.binary_sensor" not in text
    assert "type: conditional" not in text


def test_ups_dashboard_keeps_current_shutdown_policy_observation_read_only():
    text = _text()

    assert "sensor.dh_app_pve_ups_shutdown_policy" in text
    assert "sensor.dh_app_pve_ups_policy_on_battery_delay" in text
    assert "sensor.dh_app_pve_ups_policy_power_restore_delay" in text
    assert "button.dh_app_pve_ups_apply_policy" not in text


def test_ups_dashboard_contains_no_legacy_public_entity_ids():
    text = _text()

    assert ".dh_pve_ups_" not in text
    assert ".dh_ups_" not in text
