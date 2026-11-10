"""Fan dashboard charts use simple Auto-Entities filters, not frontend Jinja scans."""
from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "examples" / "dh_pve_agent_dashboard_ru.yaml"


def _text():
    return DASHBOARD.read_text(encoding="utf-8")


def _chart_blocks():
    text = _text().split("heading: CPU / RAM / Swap / Fans · 24 часа", 1)[1]
    text = text.split("heading: Частота CPU · 24 часа", 1)[0]
    percent, raw_rpm = text.split("# Raw RPM is always a separate history chart", 1)
    return percent, raw_rpm


def test_ru_dashboard_presents_fan_percent_as_primary_metric_with_rpm_fallback():
    text = _text()
    assert "fan.entity_id | replace('_rpm', '_speed')" in text
    assert "speed ~ '%" in text
    assert "~ rpm ~ ' RPM'" in text


def test_percent_graph_filters_only_numeric_rpm_percent_and_includes_cpu_ram_swap():
    percent, _ = _chart_blocks()
    assert "card_param: entities" in percent
    assert "lower_bound: 0" in percent
    assert "upper_bound: 100" in percent
    for entity in ("sensor.dh_pve_agent_cpu_usage",
                   "sensor.dh_pve_agent_memory_usage",
                   "sensor.dh_pve_agent_swap_usage"):
        assert entity in percent
    assert 'entity_id: "sensor.dh_pve_agent_fan_*_rpm_percent"' in percent
    assert 'state: ">= 0"' not in percent
    assert "filter:\n          include:" in percent
    assert "template:" not in percent


def test_rpm_graph_always_uses_raw_rpm_without_percent_dependency():
    _, raw_rpm = _chart_blocks()
    assert "name: Вентиляторы · RPM" in raw_rpm
    assert "card_param: entities" in raw_rpm
    assert "lower_bound: 0" in raw_rpm
    assert "upper_bound: 100" not in raw_rpm
    assert 'entity_id: "sensor.dh_pve_agent_fan_*_rpm"' in raw_rpm
    assert 'state: ">= 0"' in raw_rpm
    assert "template:" not in raw_rpm
    assert "percent_id" not in raw_rpm


def test_ru_dashboard_empty_fan_state_is_not_false_hardware_alarm():
    text = _text()
    assert "'primary': 'Fan: Not detected'" not in text
    assert "'primary': 'Нет данных RPM'" in text


def test_ru_dashboard_shows_manual_max_rpm_number_box():
    text = _text()
    assert "fan.entity_id | replace('sensor.', 'number.')" in text
    assert "'name': '100% RPM'" in text
    assert "button.dh_pve_agent_calibrate_fans" not in text
