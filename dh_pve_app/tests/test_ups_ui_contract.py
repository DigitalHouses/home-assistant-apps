from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "examples" / "dh_pve_ups_dashboard.yaml"


def test_ups_dashboard_example_exists_and_uses_real_entities():
    assert DASHBOARD.is_file()
    text = DASHBOARD.read_text(encoding="utf-8")

    required = (
        "sensor.dh_pve_ups_problems",
        "sensor.dh_pve_ups_status",
        "sensor.dh_pve_ups_battery_charge",
        "sensor.dh_pve_ups_battery_runtime_minutes",
        "sensor.dh_pve_ups_load",
        "sensor.dh_pve_ups_input_voltage",
        "sensor.dh_pve_ups_output_voltage",
        "sensor.dh_pve_ups_shutdown_readiness",
        "sensor.dh_pve_ups_guest_shutdown_budget",
        "button.dh_pve_ups_refresh",
    )
    for entity_id in required:
        assert entity_id in text

    assert "sensor.dh_pve_ups_estimated_real_power" not in text
    assert "estimated_real_power" not in text


def test_ups_dashboard_uses_python_problem_summary_for_top_status():
    text = DASHBOARD.read_text(encoding="utf-8")

    assert "entity: sensor.dh_pve_ups_problems" in text
    assert "state_attr(entity, 'severity')" in text
    assert "state_attr(entity, 'details')" in text
    assert "Проблем не обнаружено" not in text
    assert "type: conditional" not in text


def test_dashboard_uses_python_runtime_minutes_without_template_conversion():
    text = DASHBOARD.read_text(encoding="utf-8")

    assert "entity: sensor.dh_pve_ups_battery_runtime_minutes" in text
    assert "name: Прогноз работы от батареи" in text
    assert "/ 60" not in text


def test_fault_binary_sensors_are_visible_and_included_in_event_log():
    text = DASHBOARD.read_text(encoding="utf-8")

    for entity_id in (
        "binary_sensor.dh_pve_ups_on_battery",
        "binary_sensor.dh_pve_ups_low_battery",
        "binary_sensor.dh_pve_ups_overload",
        "binary_sensor.dh_pve_ups_replace_battery",
        "binary_sensor.dh_pve_ups_bypass",
    ):
        assert entity_id in text

    assert "title: События ИБП" in text


def test_shutdown_policy_is_read_only_in_home_assistant_dashboard():
    text = DASHBOARD.read_text(encoding="utf-8")

    assert "sensor.dh_pve_ups_shutdown_policy" in text
    assert "sensor.dh_pve_ups_policy_on_battery_delay" in text
    assert "sensor.dh_pve_ups_policy_power_restore_delay" in text
    assert "button.dh_pve_ups_apply_policy" not in text
    assert "number.dh_pve_ups_policy_on_battery_delay" not in text
    assert "number.dh_pve_ups_policy_power_restore_delay" not in text


def test_shutdown_readiness_uses_dedicated_backend_entities_and_status_colors():
    text = DASHBOARD.read_text(encoding="utf-8")

    assert "heading: Готовность аварийного shutdown" in text
    assert "entity: sensor.dh_pve_ups_shutdown_readiness" in text
    assert "entity: sensor.dh_pve_ups_guest_shutdown_budget" in text
    assert "state_attr(entity, 'issues')" in text
    assert "is_state(entity, 'ok')" in text
    assert "is_state(entity, 'warning')" in text
    assert "mdi:shield-check" in text
    assert "mdi:shield-alert" in text
    assert "VM/LXC budget" in text
    assert "state_attr(entity, 'guest_shutdown_budget_seconds')" not in text
