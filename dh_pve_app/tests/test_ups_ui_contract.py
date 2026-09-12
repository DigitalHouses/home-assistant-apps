from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "examples" / "dh_ups_dashboard.yaml"


def test_ups_dashboard_example_exists_and_uses_real_entities():
    assert DASHBOARD.is_file()
    text = DASHBOARD.read_text(encoding="utf-8")

    required = (
        "sensor.dh_ups_status",
        "sensor.dh_ups_battery_charge",
        "sensor.dh_ups_battery_runtime",
        "sensor.dh_ups_load",
        "sensor.dh_ups_input_voltage",
        "sensor.dh_ups_output_voltage",
        "binary_sensor.dh_ups_available",
        "button.dh_ups_refresh",
    )
    for entity_id in required:
        assert entity_id in text

    assert "sensor.dh_ups_estimated_real_power" not in text
    assert "estimated_real_power" not in text


def test_ups_dashboard_surfaces_only_actionable_fault_flags():
    text = DASHBOARD.read_text(encoding="utf-8")

    for entity_id in (
        "binary_sensor.dh_ups_on_battery",
        "binary_sensor.dh_ups_low_battery",
        "binary_sensor.dh_ups_overload",
        "binary_sensor.dh_ups_replace_battery",
        "binary_sensor.dh_ups_bypass",
    ):
        assert entity_id in text
