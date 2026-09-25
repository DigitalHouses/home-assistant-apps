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
        "sensor.dh_app_pve_system",
        "sensor.dh_app_pve_last_boot",
        "sensor.dh_app_pve_agent_started",
        "sensor.dh_app_pve_cpu_usage",
        "sensor.dh_app_pve_cpu_temperature",
        "sensor.dh_app_pve_cpu_frequency",
        "sensor.dh_app_pve_memory_usage",
        "sensor.dh_app_pve_swap_usage",
        "sensor.dh_app_pve_vms",
        "sensor.dh_app_pve_lxcs",
        "button.dh_app_pve_refresh",
        "sensor.dh_app_pve_last_refresh",
        "sensor.dh_app_pve_last_publication",
    ):
        assert entity_id in text


def test_dashboard_shows_app_version_in_system_card_and_hides_unknown_values():
    text = _text()
    system_card = text.split(
        "entity: sensor.dh_app_pve_system", 1
    )[1].split("icon: mdi:server", 1)[0]

    assert "sensor.dh_app_pve_app_version" in system_card
    assert "App " in system_card
    assert "unknown" in system_card
    assert "unavailable" in system_card


def test_dashboard_keeps_problem_summary_first_with_full_problem_list_and_colors():
    text = _text()

    problems = text.index("entity: sensor.dh_app_pve_problems")
    system = text.index("entity: sensor.dh_app_pve_system")
    assert problems < system

    first_column = text.split("heading: Производительность", 1)[0]
    for token in (
        "type: custom:mushroom-template-card",
        "state_attr('sensor.dh_app_pve_problems', 'active')",
        "item.object_name",
        "item.summary",
        "green",
        "red",
    ):
        assert token in first_column


def test_dashboard_uses_explicit_cards_for_singleton_host_metrics():
    text = _text()
    performance = text.split("heading: Производительность", 1)[1].split(
        "heading: Хранилища", 1
    )[0]

    assert "custom:auto-entities" not in performance
    for entity_id in (
        "sensor.dh_app_pve_cpu_usage",
        "sensor.dh_app_pve_cpu_temperature",
        "sensor.dh_app_pve_cpu_frequency",
        "sensor.dh_app_pve_memory_usage",
        "sensor.dh_app_pve_swap_usage",
    ):
        assert entity_id in performance


def test_dashboard_uses_auto_entities_only_for_dynamic_inventory_collections():
    text = _text()

    assert text.count("type: custom:auto-entities") == 4
    for token in (
        "proxmox_section: storage",
        "proxmox_section: disk",
        "proxmox_section: guests",
        "proxmox_subject: vm",
        "proxmox_subject: lxc",
        "proxmox_sort_key",
    ):
        assert token in text

    assert "entity_id: sensor.dh_app_pve_storage_*_percent_used" in text
    assert "entity_id: sensor.dh_app_pve_disk_*_temperature" in text


def test_dashboard_color_contract_uses_app_owned_problem_state():
    text = _text()

    for token in (
        "binary_sensor.dh_app_pve_cpu_temperature_problem",
        "_percent_used_problem",
        "_temperature_problem",
    ):
        assert token in text

    assert "icon_color:" in text
    assert "blue" in text
    assert "green" in text
    assert "red" in text

    # Presentation may map App-owned problem state to a color, but must not
    # calculate thresholds independently in Lovelace.
    for forbidden in (
        "storage_threshold",
        "temp_percent",
        "> states('number.dh_app_pve_",
        ">= states('number.dh_app_pve_",
    ):
        assert forbidden not in text


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
    assert "storage_threshold" not in text
    assert "temp_percent" not in text


def test_dashboard_contains_no_legacy_public_entity_ids():
    text = _text()

    assert ".dh_pve_" not in text
    assert ".digitalhouses_proxmox_" not in text
