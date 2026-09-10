from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "examples" / "dh_pve_dashboard.yaml"


def _text() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def test_dashboard_file_exists_and_uses_required_cards():
    assert DASHBOARD.exists()
    text = _text()
    assert "type: sections" in text
    assert "custom:mushroom-template-card" in text
    assert "custom:auto-entities" in text
    assert "custom:mini-graph-card" in text
    assert "custom:entity-progress-card-template" in text


def test_dashboard_is_exactly_four_continuous_columns():
    text = _text()
    assert text.count("  - type: grid\n    cards:") == 4
    for heading in (
        "Хост",
        "Состояние Proxmox",
        "Производительность",
        "Система",
        "Диагностика дисков",
        "Диски и хранилища",
        "Физические диски",
        "Хранилища Proxmox",
        "Настройки мониторинга",
        "Оборудование",
        "CPU / RAM / Swap",
        "CPU & Throttling",
        "Охлаждение",
        "Графика",
        "VM / LXC",
        "История",
    ):
        assert f"heading: {heading}" in text


def test_dashboard_uses_new_dh_pve_contract_only():
    text = _text()
    assert "sensor.dh_pve_cpu_usage" in text
    assert "sensor.dh_pve_memory_usage" in text
    assert "button.dh_pve_refresh" in text
    assert "proxmox_integration: dh_pve_app" in text
    assert "digitalhouses_proxmox_" not in text
    assert "sensor.digitalhouses_proxmox" not in text
    assert "input_number.dh_proxmox" not in text


def test_dashboard_dynamic_sections_use_semantic_attributes():
    text = _text()
    for section in (
        "storage",
        "disk",
        "graphics",
        "cooling",
        "guests",
        "settings",
        "diagnostic",
    ):
        assert f"proxmox_section: {section}" in text
    assert "proxmox_sort_key" in text
    assert "proxmox_metric: health" in text
    assert "proxmox_metric: owner" in text
    assert "proxmox_metric: status" in text


def test_dashboard_exposes_read_only_guest_inventory():
    text = _text()
    assert "sensor.dh_pve_vms" in text
    assert "sensor.dh_pve_lxcs" in text
    assert "proxmox_section: guests" in text
    assert "proxmox_subject: vm" in text
    assert "proxmox_subject: lxc" in text
    assert "command_topic" not in text
    assert "switch.dh_pve_vm_" not in text
    assert "button.dh_pve_vm_" not in text


def test_dashboard_storage_is_used_total_not_free_space():
    text = _text()
    assert "used_gib" in text
    assert "total_gib" in text
    assert "available_gib" not in text
    assert "disk_free" not in text


def test_dashboard_health_and_cooling_use_python_results():
    text = _text()
    assert "sensor.dh_pve_fans" in text
    assert "HEALTHY" in text
    assert "WARNING" in text
    assert "CRITICAL" in text
    assert "| count" not in text


def test_dashboard_does_not_recompute_infrastructure_health_in_ha():
    text = _text()
    assert "selectattr(" not in text
    assert "Overall" not in text
    assert "total - free" not in text
