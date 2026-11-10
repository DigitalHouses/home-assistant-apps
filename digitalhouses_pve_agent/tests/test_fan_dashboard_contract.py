"""Fan dashboard charts use simple Auto-Entities filters, not frontend Jinja scans."""
from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "examples" / "dh_pve_agent_dashboard_ru.yaml"


def _text():
    return DASHBOARD.read_text(encoding="utf-8")


def _chart_blocks():
    import yaml
    dashboard = yaml.safe_load(_text())
    charts = {
        card["card"]["name"]: card
        for section in dashboard["sections"]
        for card in section["cards"]
        if card.get("type") == "custom:auto-entities"
        and card.get("card", {}).get("type") == "custom:mini-graph-card"
        and card["card"].get("name") in (
            "CPU / RAM / Swap / Fans", "Вентиляторы · RPM"
        )
    }
    assert set(charts) == {"CPU / RAM / Swap / Fans", "Вентиляторы · RPM"}
    return charts


def test_ru_dashboard_presents_fan_percent_as_primary_metric_with_rpm_fallback():
    text = _text()
    assert "fan.entity_id | replace('_rpm', '_speed')" in text
    assert "speed ~ '%" in text
    assert "~ rpm ~ ' RPM'" in text


def test_percent_graph_filters_only_numeric_rpm_percent_and_includes_cpu_ram_swap():
    chart = _chart_blocks()["CPU / RAM / Swap / Fans"]
    assert chart["card_param"] == "entities"
    assert chart["card"]["lower_bound"] == 0
    assert chart["card"]["upper_bound"] == 100
    assert chart["entities"] == [
        {"entity": "sensor.dh_pve_agent_cpu_usage", "name": "CPU"},
        {"entity": "sensor.dh_pve_agent_memory_usage", "name": "RAM"},
        {"entity": "sensor.dh_pve_agent_swap_usage", "name": "Swap"},
    ]
    assert chart["filter"] == {"include": [
        {"entity_id": "sensor.dh_pve_agent_fan_*_rpm_percent",
         "state": ">= 0"}
    ]}
    assert "template" not in chart["filter"]


def test_rpm_graph_always_uses_raw_rpm_without_percent_dependency():
    chart = _chart_blocks()["Вентиляторы · RPM"]
    assert chart["card_param"] == "entities"
    assert chart["card"]["lower_bound"] == 0
    assert "upper_bound" not in chart["card"]
    assert chart["filter"] == {"include": [
        {"entity_id": "sensor.dh_pve_agent_fan_*_rpm",
         "state": ">= 0"}
    ]}
    assert "template" not in chart["filter"]


def test_ru_dashboard_empty_fan_state_is_not_false_hardware_alarm():
    text = _text()
    assert "'primary': 'Fan: Not detected'" not in text
    assert "'primary': 'Нет данных RPM'" in text


def test_ru_dashboard_shows_manual_max_rpm_number_box():
    text = _text()
    assert "fan.entity_id | replace('sensor.', 'number.')" in text
    assert "'name': '100% RPM'" in text
    assert "button.dh_pve_agent_calibrate_fans" not in text
