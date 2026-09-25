from pathlib import Path

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "examples" / "packages" / "dh_app_pve_package.yaml"


def _text() -> str:
    return PACKAGE.read_text(encoding="utf-8")


def test_package_records_only_explicit_canonical_time_series():
    assert PACKAGE.exists()
    text = _text()

    assert "dh_app_pve_package:" in text
    assert "recorder:" in text
    assert "entities:" in text

    for entity_id in (
        "sensor.dh_app_pve_cpu_usage",
        "sensor.dh_app_pve_cpu_temperature",
        "sensor.dh_app_pve_cpu_frequency",
        "sensor.dh_app_pve_memory_usage",
        "sensor.dh_app_pve_swap_usage",
        "sensor.dh_app_pve_ups_status",
        "binary_sensor.dh_app_pve_ups_line_power",
        "sensor.dh_app_pve_ups_battery_charge",
        "sensor.dh_app_pve_ups_battery_runtime_minutes",
        "sensor.dh_app_pve_ups_load",
        "sensor.dh_app_pve_ups_input_voltage",
        "sensor.dh_app_pve_ups_output_voltage",
        "sensor.dh_app_pve_ups_battery_voltage",
    ):
        assert entity_id in text

    for entity_glob in (
        "sensor.dh_app_pve_fan_*_speed",
        "sensor.dh_app_pve_disk_*_temperature",
        "sensor.dh_app_pve_disk_*_wear",
        "sensor.dh_app_pve_storage_*_percent_used",
        "sensor.dh_app_pve_gpu_*_temperature",
        "sensor.dh_app_pve_gpu_*_transcoding",
    ):
        assert entity_glob in text

    recorder = text.split("  logbook:", 1)[0]
    assert "sensor.dh_app_pve_*" not in recorder
    assert "binary_sensor.dh_app_pve_*" not in recorder
    assert "event.dh_app_pve_" not in recorder
    assert "sensor.dh_pve_" not in recorder
    assert "binary_sensor.dh_pve_" not in recorder


def test_ups_status_and_line_power_are_explicitly_kept_in_logbook():
    text = _text()

    assert "logbook:" in text
    assert "sensor.dh_app_pve_ups_status" in text
    assert "binary_sensor.dh_app_pve_ups_line_power" in text


def test_package_keeps_problem_and_threshold_decisions_in_app():
    text = _text()

    # UI-only snapshot helpers and the config_changed acknowledgement automation
    # are allowed in the consolidated base package. They must not recreate
    # problem calculation, polling or threshold decision logic in HA.
    assert "dh_app_pve_ups_trigger_snapshot_charge:" in text
    assert "dh_app_pve_ups_trigger_snapshot_reserve:" in text
    assert "dh_app_pve_ups_trigger_close_after_success" in text
    assert "\n  template:" not in text
    assert "recorder.purge_entities" not in text
    assert "time_pattern" not in text
    assert "dh_proxmox_" not in text
