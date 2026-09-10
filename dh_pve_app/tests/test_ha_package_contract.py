from pathlib import Path

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "examples" / "packages" / "dh_app_proxmox_package.yaml"


def _text() -> str:
    return PACKAGE.read_text(encoding="utf-8")


def test_package_exists_and_records_new_dh_pve_entities():
    assert PACKAGE.exists()
    text = _text()
    assert "dh_app_proxmox_package:" in text
    assert "recorder:" in text
    assert "sensor.dh_pve_*" in text
    assert "binary_sensor.dh_pve_*" in text
    assert "sensor.digitalhouses_proxmox_*" not in text
    assert "binary_sensor.digitalhouses_proxmox_*" not in text


def test_package_keeps_v7_threshold_helpers():
    text = _text()
    for entity in (
        "dh_proxmox_storage_usage_threshold:",
        "dh_proxmox_cpu_temperature_threshold:",
        "dh_proxmox_hdd_temperature_threshold:",
        "dh_proxmox_ssd_temperature_threshold:",
        "dh_proxmox_nvme_temperature_threshold:",
        "dh_proxmox_gpu_temperature_threshold:",
    ):
        assert entity in text


def test_package_initializes_threshold_defaults_without_periodic_trigger():
    text = _text()
    assert "event: start" in text
    for default in ("value: 80", "value: 90", "value: 45", "value: 75", "value: 85"):
        assert default in text
    assert "time_pattern" not in text
    assert "platform: time" not in text


def test_package_does_not_recreate_old_aggregate_health_templates():
    text = _text()
    assert "dh_proxmox_storages_over_threshold_count" not in text
    assert "dh_proxmox_temperatures_over_threshold_count" not in text
    assert "dh_proxmox_storage_capacity_problem" not in text
    assert "dh_proxmox_temperature_problem" not in text
    assert "recorder.purge_entities" not in text
