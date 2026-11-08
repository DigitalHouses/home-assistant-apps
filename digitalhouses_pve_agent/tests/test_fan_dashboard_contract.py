"""Lovelace fan charts must use the actual auto-entities template contract."""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from importlib.util import find_spec

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "examples" / "dh_pve_agent_dashboard_ru.yaml"


def _text():
    return DASHBOARD.read_text(encoding="utf-8")


def _chart_blocks():
    text = _text()
    part = text.split("heading: CPU / RAM / Swap / Fans · 24 часа", 1)[1]
    part = part.split("heading: Частота CPU · 24 часа", 1)[0]
    percent, rpm = part.split("# Separate RPM-only chart", 1)
    return percent, rpm


def test_ru_dashboard_presents_fan_percent_as_primary_metric_with_rpm_fallback():
    text = _text()
    assert "fan.entity_id | replace('_rpm', '_speed')" in text
    assert "speed ~ '%" in text
    assert "~ rpm ~ ' RPM'" in text


def test_percent_graph_keeps_static_cpu_ram_swap_and_only_dynamic_percent_entity_ids():
    percent, rpm = _chart_blocks()
    assert "proxmox_metric') == 'speed_percent'" in percent
    assert "proxmox_metric') == 'rpm'" not in percent
    assert "card_param: entities" in percent
    assert "type: custom:mini-graph-card" in percent
    assert "lower_bound: 0" in percent
    assert "upper_bound: 100" in percent
    assert "y_axis" not in percent
    assert "{{ fan.entity_id }}" in percent
    assert "{{ ns.items }}" not in percent
    for entity in (
        "sensor.dh_pve_agent_cpu_usage",
        "sensor.dh_pve_agent_memory_usage",
        "sensor.dh_pve_agent_swap_usage",
    ):
        assert entity in percent


def test_rpm_graph_is_direct_mini_graph_and_no_nested_json_cards():
    percent, rpm = _chart_blocks()
    assert "type: custom:auto-entities" in rpm
    assert "show_empty: false" in rpm
    assert "card_param: entities" in rpm
    assert "type: custom:mini-graph-card" in rpm
    assert "card_param: cards" not in rpm
    assert "type: grid" not in rpm
    assert "proxmox_metric') == 'rpm'" in rpm
    assert "fan.state | is_number" in rpm
    assert "percent_id = fan.entity_id | replace('_rpm', '_speed')" in rpm
    assert "not (states(percent_id) | is_number)" in rpm
    assert "{{ fan.entity_id }}" in rpm
    assert "| tojson" not in rpm
    assert "{{ [{" not in rpm
    assert "lower_bound: 0" in rpm
    assert "upper_bound: 100" not in rpm
    assert "y_axis" not in rpm


def test_both_graph_templates_produce_only_plain_entity_ids_for_frontend():
    if find_spec("jinja2") is None or find_spec("yaml") is None:
        return

    import jinja2
    import yaml

    document = yaml.safe_load(_text())
    charts = [
        c
        for sec in document["sections"]
        for c in sec["cards"]
        if c.get("type") == "custom:auto-entities"
        and c.get("card", {}).get("name") in {
            "CPU / RAM / Swap / Fans",
            "Вентиляторы · RPM (без калибровки)",
        }
    ]
    assert len(charts) == 2
    chart_by_name = {c["card"]["name"]: c for c in charts}
    percent = chart_by_name["CPU / RAM / Swap / Fans"]
    rpm = chart_by_name["Вентиляторы · RPM (без калибровки)"]
    base = [
        {"entity": "sensor.dh_pve_agent_cpu_usage", "name": "CPU"},
        {"entity": "sensor.dh_pve_agent_memory_usage", "name": "RAM"},
        {"entity": "sensor.dh_pve_agent_swap_usage", "name": "Swap"},
    ]
    assert percent["entities"] == base
    assert percent["card"]["lower_bound"] == 0
    assert percent["card"]["upper_bound"] == 100
    assert rpm["card"]["lower_bound"] == 0
    assert "upper_bound" not in rpm["card"]

    def is_number(value):
        try:
            return float(value) == float(value)
        except (ValueError, TypeError):
            return False

    class FakeStates:
        def __init__(self, sensors, by_id):
            self.sensor = sensors
            self._by_id = by_id

        def __call__(self, entity_id):
            return self._by_id.get(entity_id, "unknown")

    def rendered_ids(card, rows):
        sensors = []
        attrs = {}
        values = {}
        for entity, value, metric, name, integration in rows:
            sensors.append(SimpleNamespace(entity_id=entity, state=value, name=name))
            values[entity] = value
            attrs[entity] = {
                "proxmox_integration": integration,
                "proxmox_section": "cooling",
                "proxmox_metric": metric,
                "proxmox_display_name": name,
            }
        template = jinja2.Environment().from_string(card["filter"]["template"])
        template.environment.filters["is_number"] = is_number
        result = template.render(
            states=FakeStates(sensors, values),
            state_attr=lambda entity, key: attrs.get(entity, {}).get(key),
        )
        # Matches lovelace-auto-entities _renderer string handling:
        # tpl.split(/[\\s,]+/) => individual entity IDs, never JSON objects.
        values = [v for v in re.split(r"[\s,]+", result) if v]
        assert all(re.fullmatch(r"sensor\.[a-z0-9_]+", v) for v in values), values
        return values

    assert rendered_ids(percent, []) == []
    assert rendered_ids(rpm, []) == []
    rows = [
        ("sensor.pve_fan1_speed", "unavailable", "speed_percent", "FAN1", "digitalhouses_pve_agent"),
        ("sensor.pve_fan1_rpm", "1700", "rpm", "FAN1", "digitalhouses_pve_agent"),
        ("sensor.pve_fan3_rpm", "0", "rpm", "FAN3", "digitalhouses_pve_agent"),
        ("sensor.pve_fan2_rpm", "2200", "rpm", "FAN2", "digitalhouses_pve_agent"),
        ("sensor.pve_fan2_speed", "62", "speed_percent", "FAN2", "digitalhouses_pve_agent"),
        ("sensor.pve_fan9_rpm", "unavailable", "rpm", "FAN9", "digitalhouses_pve_agent"),
        ("sensor.elsewhere_fan_rpm", "2700", "rpm", "Other", "elsewhere"),
    ]
    assert rendered_ids(percent, rows) == ["sensor.pve_fan2_speed"]
    assert rendered_ids(rpm, rows) == ["sensor.pve_fan1_rpm", "sensor.pve_fan3_rpm"]
    # Numeric 0% is calibrated and removes this fan from the RPM fallback.
    rows.extend([
        ("sensor.pve_fan1_speed", "0", "speed_percent", "FAN1", "digitalhouses_pve_agent"),
        ("sensor.pve_fan3_speed", "47", "speed_percent", "FAN3", "digitalhouses_pve_agent"),
    ])
    assert rendered_ids(percent, rows) == [
        "sensor.pve_fan1_speed", "sensor.pve_fan2_speed", "sensor.pve_fan3_speed"
    ]
    assert rendered_ids(rpm, rows) == []


def test_ru_dashboard_empty_fan_state_is_not_false_hardware_alarm():
    text = _text()
    assert "'primary': 'Fan: Not detected'" not in text
    assert "'primary': 'Нет данных RPM'" in text


def test_ru_dashboard_requires_confirmation_before_manual_fan_calibration():
    text = _text()
    assert "button.dh_pve_agent_calibrate_fans" in text
    assert "confirmation:" in text
    assert "максимальную скорость" in text
    assert "автоматическое" in text
    assert "button.press" in text
