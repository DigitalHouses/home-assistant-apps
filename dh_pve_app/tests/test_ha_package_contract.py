from pathlib import Path

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "examples" / "packages" / "dh_app_pve_package.yaml"


def _text() -> str:
    return PACKAGE.read_text(encoding="utf-8")


def test_package_exists_and_records_new_dh_pve_entities():
    assert PACKAGE.exists()
    text = _text()
    assert "dh_app_pve_package:" in text
    assert "recorder:" in text
    assert "sensor.dh_pve_*" in text
    assert "binary_sensor.dh_pve_*" in text
    assert "number.dh_pve_ups_*" in text
    assert "time.dh_pve_ups_*" in text
    assert "sensor.digitalhouses_proxmox_*" not in text
    assert "binary_sensor.digitalhouses_proxmox_*" not in text
    assert "dh_app_proxmox_package:" not in text


def test_package_has_no_duplicate_threshold_helpers_or_initializer():
    text = _text()

    assert "input_number:" not in text
    assert "automation:" not in text
    assert "dh_pve_initialize_thresholds" not in text
    assert "storage_usage_threshold" not in text
    assert "_temperature_threshold" not in text
    assert "dh_proxmox_" not in text


def test_package_does_not_recreate_old_aggregate_health_templates():
    text = _text()
    assert "storages_over_threshold_count" not in text
    assert "temperatures_over_threshold_count" not in text
    assert "storage_capacity_problem" not in text
    assert "temperature_problem" not in text
    assert "recorder.purge_entities" not in text
    assert "time_pattern" not in text
    assert "platform: time" not in text
