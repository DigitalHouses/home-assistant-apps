from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "examples" / "dh_app_pve_ups_dashboard.yaml"


def _text() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def test_ups_dashboard_uses_canonical_status_and_telemetry():
    assert DASHBOARD.is_file()
    text = _text()

    for entity_id in (
        "sensor.dh_app_pve_ups_problems",
        "sensor.dh_app_pve_ups_status",
        "sensor.dh_app_pve_ups_battery_charge",
        "sensor.dh_app_pve_ups_battery_runtime_minutes",
        "sensor.dh_app_pve_ups_load",
        "sensor.dh_app_pve_ups_input_voltage",
        "sensor.dh_app_pve_ups_output_voltage",
        "button.dh_app_pve_ups_refresh",
    ):
        assert entity_id in text


def test_ups_dashboard_uses_app_owned_problem_state():
    text = _text()

    for entity_id in (
        "binary_sensor.dh_app_pve_ups_nut_unavailable_problem",
        "binary_sensor.dh_app_pve_ups_on_battery_problem",
        "binary_sensor.dh_app_pve_ups_low_battery_problem",
        "binary_sensor.dh_app_pve_ups_overload_problem",
        "binary_sensor.dh_app_pve_ups_replace_battery_problem",
        "binary_sensor.dh_app_pve_ups_bypass_problem",
        "binary_sensor.dh_app_pve_ups_power_state_unknown_problem",
    ):
        assert entity_id in text

    # Conditional cards are presentation-only in Trigger v2. Problem decisions
    # still come from App-owned entities; HA must not scan entity registries or
    # rebuild the problem engine locally.
    assert "states.binary_sensor" not in text
    assert "custom:auto-entities" not in text


def test_ups_dashboard_keeps_nut_observation_and_uses_trigger_v2_policy_view():
    text = _text()

    assert "sensor.dh_app_pve_ups_shutdown_policy" in text
    assert "sensor.dh_app_pve_ups_policy_power_restore_delay" in text
    assert "sensor.dh_app_pve_ups_policy_on_battery_delay" not in text
    assert "Config UPS trigger" in text
    assert "button.dh_app_pve_ups_apply_policy" not in text


def test_ups_dashboard_has_permanent_app_owned_line_power_monthly_statistics():
    text = _text()

    for entity_id in (
        "binary_sensor.dh_app_pve_ups_line_power",
        "sensor.dh_app_pve_ups_line_power_online_month",
        "sensor.dh_app_pve_ups_line_power_offline_month",
        "sensor.dh_app_pve_ups_line_power_outages_month",
        "sensor.dh_app_pve_ups_line_power_availability_month",
        "sensor.dh_app_pve_ups_line_power_current_outage_started",
    ):
        assert entity_id in text

    for label in (
        "Городская сеть работает",
        "Городская сеть отсутствует",
        "Состояние городской сети неизвестно",
        "Статистика за",
        "Свет был",
        "Света не было",
        "Отключений",
        "Доступность",
    ):
        assert label in text

    # The month title/partial-month note come from App metadata. HA only formats
    # ready state; it must not reconstruct monthly accounting from history.
    assert "month_label_ru" in text
    assert "partial_month" in text
    assert "tracking_since" in text
    assert "history_stats" not in text
    assert "recorder" not in text.casefold()

    monthly = text.split("Статистика за", 1)[1]
    assert "type: conditional" not in monthly.split("heading: UPS Shutdown Trigger", 1)[0]


def test_ups_dashboard_contains_no_legacy_public_entity_ids():
    text = _text()

    assert ".dh_pve_ups_" not in text
    assert ".dh_ups_" not in text