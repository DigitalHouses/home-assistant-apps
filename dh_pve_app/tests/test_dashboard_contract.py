from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "examples" / "dh_pve_dashboard.yaml"


def _text() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def test_dashboard_file_exists_and_uses_legacy_v7_card_stack():
    assert DASHBOARD.exists()
    text = _text()
    assert "type: sections" in text
    assert "icon: phu:proxmox" in text
    assert "custom:mushroom-template-card" in text
    assert "custom:mushroom-entity-card" in text
    assert "custom:mushroom-number-card" in text
    assert "custom:auto-entities" in text
    assert "custom:mini-graph-card" in text
    assert "custom:entity-progress-card-template" in text


def test_dashboard_is_exactly_four_continuous_columns_with_v7_headings():
    text = _text()
    assert text.count("  - type: grid\n    cards:") == 4
    for heading in (
        "Состояние Proxmox",
        "Производительность",
        "Система",
        "Диагностика дисков",
        "Диски и хранилища",
        "Физические диски",
        "Хранилища Proxmox",
        "Пороги уведомлений",
        "Оборудование",
        "CPU / RAM / Swap",
        "CPU & Throttling",
        "Охлаждение",
        "Графика",
        "VM / LXC",
        "История",
        "Температуры · 24 часа",
        "CPU / RAM / Swap · 24 часа",
        "Частота CPU · 24 часа",
        "Использование хранилищ · 7 дней",
    ):
        assert f"heading: {heading}" in text


def test_dashboard_uses_new_dh_pve_entities_and_semantics_only():
    text = _text()
    assert "sensor.dh_pve_cpu_usage" in text
    assert "section == 'memory'" in text
    assert "subject == 'memory'" in text
    assert "sensor.dh_pve_cpu_temperature" in text
    assert "sensor.dh_pve_cpu_frequency" in text
    assert "binary_sensor.dh_pve_cpu_throttling" in text
    assert "button.dh_pve_refresh" in text
    assert "proxmox_integration: dh_pve_app" in text
    assert "digitalhouses_proxmox_" not in text
    assert "sensor.digitalhouses_proxmox" not in text
    assert "proxmox_integration: digitalhouses_proxmox" not in text


def test_dashboard_preserves_v7_overall_problem_card_and_alert_colors():
    text = _text()
    assert "Проблем не обнаружено" in text
    assert "Обнаружено проблем:" in text
    assert "Система работает штатно." in text
    assert "Заполнение хранилища выше порога" in text
    assert "Температура выше порога" in text
    assert "SMART ERROR" in text
    assert "CPU throttling" in text
    assert "mdi:check-circle" in text
    assert "mdi:alert-circle" in text
    assert "'red' if" in text
    assert "'green'" in text


def test_dashboard_preserves_notification_threshold_controls_as_ui_only():
    text = _text()
    assert "UI/notification thresholds only" in text
    for entity_id in (
        "input_number.dh_proxmox_storage_usage_threshold",
        "input_number.dh_proxmox_cpu_temperature_threshold",
        "input_number.dh_proxmox_hdd_temperature_threshold",
        "input_number.dh_proxmox_ssd_temperature_threshold",
        "input_number.dh_proxmox_nvme_temperature_threshold",
        "input_number.dh_proxmox_gpu_temperature_threshold",
    ):
        assert entity_id in text
    for fallback in ("else 80", "else 90", "else 45", "else 75", "else 85"):
        assert fallback in text


def test_physical_disk_cards_keep_v7_type_icons_but_color_from_python_health():
    text = _text()
    assert "proxmox_metric') == 'health'" in text
    assert "HEALTHY" in text
    assert "WARNING" in text
    assert "CRITICAL" in text
    assert "SMART: OK" in text
    assert "SMART: ERROR" in text
    assert "mdi:expansion-card" in text
    assert "mdi:chip" in text
    assert "mdi:harddisk" in text
    assert "'orange'" in text
    assert "health.state == 'CRITICAL'" in text
    assert "health.state == 'WARNING'" in text
    assert "health.state == 'HEALTHY'" in text


def test_physical_disk_cards_open_temperature_history_on_tap():
    text = _text()
    assert "temp_entity=health.entity_id" in text
    assert "related.temp_entity = s.entity_id" in text
    assert "'entity': related.temp_entity" in text
    assert "'tap_action': {'action': 'more-info'}" in text


def test_storage_cards_keep_v7_progress_and_red_green_logic_using_used_total():
    text = _text()
    assert "custom:entity-progress-card-template" in text
    assert "Хранилища Proxmox" in text
    assert "занято" in text
    assert "used_gib" in text
    assert "total_gib" in text
    assert "mdi:database-alert" in text
    assert "mdi:database-check" in text
    assert "bar_color" in text
    assert "free_gib" not in text
    assert "available_gib" not in text
    assert "total - free" not in text


def test_cpu_temperature_and_throttling_keep_v7_visual_logic():
    text = _text()
    assert "CPU & Throttling" in text
    assert "input_number.dh_proxmox_cpu_temperature_threshold" in text
    assert "temp_percent" in text
    assert "mdi:thermometer-alert" in text
    assert "mdi:thermometer-check" in text
    assert "binary_sensor.dh_pve_cpu_throttling" in text
    assert "Обнаружен CPU throttling." in text
    assert "CPU throttling не обнаружен." in text
    assert "mdi:speedometer-slow" in text


def test_dynamic_sections_use_new_semantic_attributes_and_guest_inventory_is_read_only():
    text = _text()
    for section in ("storage", "disk", "graphics", "cooling", "guests", "diagnostic"):
        assert section in text
    assert "proxmox_sort_key" in text
    assert "sensor.dh_pve_vms" in text
    assert "sensor.dh_pve_lxcs" in text
    assert "proxmox_subject') in ['vm', 'lxc']" in text
    assert "proxmox_metric') == 'status'" in text
    assert "switch.dh_pve_vm_" not in text
    assert "button.dh_pve_vm_" not in text


def test_history_keeps_v7_combined_graphs_and_time_windows():
    text = _text()
    assert "'name': 'Температуры'" in text
    assert "'name': 'CPU / RAM / Swap'" in text
    assert "'name': 'Частота CPU'" in text
    assert "'name': 'Хранилища'" in text
    assert "'hours_to_show': 24" in text
    assert "'hours_to_show': 168" in text
    assert "'legend': true" in text


def test_dashboard_does_not_recompute_disk_health_or_free_space():
    text = _text()
    # Disk condition/color must come from the Python health entity. Temperature
    # thresholds remain presentation/notification thresholds, not disk health.
    assert "proxmox_metric') == 'health'" in text
    assert "health.state == 'CRITICAL'" in text
    assert "health.state == 'WARNING'" in text
    assert "health.state == 'HEALTHY'" in text
    assert "total - free" not in text
