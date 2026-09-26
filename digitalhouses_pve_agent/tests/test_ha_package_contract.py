from pathlib import Path

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "examples" / "packages" / "dh_pve_agent_package.yaml"


def _text() -> str:
    return PACKAGE.read_text(encoding="utf-8")


def test_package_records_only_explicit_canonical_time_series():
    assert PACKAGE.exists()
    text = _text()

    assert "dh_pve_agent_package:" in text
    assert "recorder:" in text
    assert "entities:" in text

    for entity_id in (
        "sensor.dh_pve_agent_cpu_usage",
        "sensor.dh_pve_agent_cpu_temperature",
        "sensor.dh_pve_agent_cpu_frequency",
        "sensor.dh_pve_agent_memory_usage",
        "sensor.dh_pve_agent_swap_usage",
        "sensor.dh_pve_agent_ups_status",
        "binary_sensor.dh_pve_agent_ups_line_power",
        "sensor.dh_pve_agent_ups_battery_charge",
        "sensor.dh_pve_agent_ups_battery_runtime_minutes",
        "sensor.dh_pve_agent_ups_load",
        "sensor.dh_pve_agent_ups_input_voltage",
        "sensor.dh_pve_agent_ups_output_voltage",
        "sensor.dh_pve_agent_ups_battery_voltage",
    ):
        assert entity_id in text

    for entity_glob in (
        "sensor.dh_pve_agent_fan_*_speed",
        "sensor.dh_pve_agent_disk_*_temperature",
        "sensor.dh_pve_agent_disk_*_wear",
        "sensor.dh_pve_agent_storage_*_percent_used",
        "sensor.dh_pve_agent_gpu_*_temperature",
        "sensor.dh_pve_agent_gpu_*_transcoding",
    ):
        assert entity_glob in text

    recorder = text.split("  logbook:", 1)[0]
    assert "sensor.dh_pve_agent_*" not in recorder
    assert "binary_sensor.dh_pve_agent_*" not in recorder
    assert "event.dh_pve_agent_" not in recorder


def test_ups_status_and_line_power_are_explicitly_kept_in_logbook():
    text = _text()

    assert "logbook:" in text
    assert "sensor.dh_pve_agent_ups_status" in text
    assert "binary_sensor.dh_pve_agent_ups_line_power" in text


def test_package_keeps_problem_and_threshold_decisions_in_app():
    text = _text()

    # UI-only snapshot helpers and the config_changed acknowledgement automation
    # are allowed in the consolidated base package. They must not recreate
    # problem calculation, polling or threshold decision logic in HA.
    assert "dh_pve_agent_ups_trigger_snapshot_charge:" in text
    assert "dh_pve_agent_ups_trigger_snapshot_reserve:" in text
    assert "dh_pve_agent_ups_trigger_close_after_success" in text
    assert "\n  template:" not in text
    assert "recorder.purge_entities" not in text
    assert "time_pattern" not in text
    assert "dh_proxmox_" not in text
