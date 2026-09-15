from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "examples" / "dh_app_pve_dashboard.yaml"


def _text() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def test_canonical_pve_dashboard_exists_and_uses_app_owned_state():
    assert DASHBOARD.exists()
    text = _text()

    assert "type: sections" in text
    for entity_id in (
        "sensor.dh_app_pve_problems",
        "sensor.dh_app_pve_cpu_usage",
        "sensor.dh_app_pve_cpu_temperature",
        "sensor.dh_app_pve_cpu_frequency",
        "sensor.dh_app_pve_memory_usage",
        "sensor.dh_app_pve_swap_usage",
        "button.dh_app_pve_refresh",
    ):
        assert entity_id in text


def test_dashboard_exposes_app_owned_alert_threshold_controls():
    text = _text()

    for entity_id in (
        "number.dh_app_pve_storage_percent_used_threshold",
        "number.dh_app_pve_cpu_temperature_threshold",
        "number.dh_app_pve_hdd_temperature_threshold",
        "number.dh_app_pve_ssd_temperature_threshold",
        "number.dh_app_pve_nvme_temperature_threshold",
        "number.dh_app_pve_gpu_temperature_threshold",
    ):
        assert entity_id in text

    assert "input_number." not in text
    assert "dh_proxmox_" not in text


def test_dashboard_is_a_light_client_not_a_problem_engine():
    text = _text()

    assert "states.sensor" not in text
    assert "states.binary_sensor" not in text
    assert "custom:auto-entities" not in text
    assert "storage_threshold" not in text
    assert "temp_percent" not in text
    assert "proxmox_metric" not in text


def test_dashboard_contains_no_legacy_public_entity_ids():
    text = _text()

    assert ".dh_pve_" not in text
    assert ".digitalhouses_proxmox_" not in text
