from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "examples" / "dh_pve_agent_dashboard_ru.yaml"


def test_ru_dashboard_presents_fan_percent_as_primary_metric_with_rpm_fallback():
    text = DASHBOARD.read_text(encoding="utf-8")

    assert "fan.entity_id | replace('_rpm', '_speed')" in text
    assert "speed ~ '%" in text
    assert "~ rpm ~ ' RPM'" in text


def test_ru_dashboard_graph_uses_live_rpm_when_percent_is_unavailable():
    text = DASHBOARD.read_text(encoding="utf-8")
    graph = text.split("heading: CPU / RAM / Swap / Fans · 24 часа", 1)[1]
    graph = graph.split("heading: Частота CPU · 24 часа", 1)[0]

    assert "type: custom:auto-entities" in graph
    assert "type: custom:mini-graph-card" in graph
    assert "card_param: entities" in graph
    assert "proxmox_metric') == 'rpm'" in graph
    assert "states(speed_id) | is_number" in graph
    assert "'entity': speed_id" in graph
    assert "'entity': fan.entity_id" in graph
    assert "'y_axis': 'secondary'" in graph
    assert "lower_bound_secondary: 0" in graph
    assert "sensor.dh_pve_agent_cpu_usage" in graph
    assert "sensor.dh_pve_agent_memory_usage" in graph
    assert "sensor.dh_pve_agent_swap_usage" in graph


def test_ru_dashboard_empty_fan_state_is_not_false_hardware_alarm():
    text = DASHBOARD.read_text(encoding="utf-8")
    assert "'primary': 'Fan: Not detected'" not in text
    assert "'primary': 'Нет данных RPM'" in text


def test_ru_dashboard_requires_confirmation_before_manual_fan_calibration():
    text = DASHBOARD.read_text(encoding="utf-8")

    assert "button.dh_pve_agent_calibrate_fans" in text
    assert "confirmation:" in text
    assert "максимальную скорость" in text
    assert "автоматическое" in text
    assert "button.press" in text
