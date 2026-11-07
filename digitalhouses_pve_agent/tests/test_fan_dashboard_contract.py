from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "examples" / "dh_pve_agent_dashboard_ru.yaml"


def test_ru_dashboard_presents_fan_percent_as_primary_metric_with_rpm_fallback():
    text = DASHBOARD.read_text(encoding="utf-8")

    assert "fan.entity_id | replace('_rpm', '_speed')" in text
    assert "speed ~ '%" in text
    assert "~ rpm ~ ' RPM'" in text


def test_ru_dashboard_graph_percent_only_and_always_has_base_entities():
    from types import SimpleNamespace

    import jinja2
    import yaml

    sections = yaml.safe_load(DASHBOARD.read_text(encoding="utf-8"))["sections"]
    graphs = [
        card
        for section in sections
        for card in section["cards"]
        if card.get("card", {}).get("name") == "CPU / RAM / Swap / Fans"
    ]
    assert len(graphs) == 1
    graph = graphs[0]
    assert graph["type"] == "custom:auto-entities"
    assert graph["card"]["type"] == "custom:mini-graph-card"
    assert graph["card_param"] == "entities"
    assert graph["card"]["lower_bound"] == 0
    assert graph["card"]["upper_bound"] == 100
    assert "lower_bound_secondary" not in graph["card"]
    assert "entities" not in graph  # one source builds all graph lines

    def fake_number(value):
        try:
            return float(value) == float(value)
        except (TypeError, ValueError):
            return False

    template = jinja2.Environment().from_string(graph["filter"]["template"])
    template.environment.filters["is_number"] = fake_number

    def render(items):
        sensors = []
        attrs = {}
        for entity_id, state, metric, name, origin in items:
            sensors.append(SimpleNamespace(entity_id=entity_id, state=state, name=name))
            attrs[entity_id] = {
                "proxmox_integration": origin,
                "proxmox_section": "cooling",
                "proxmox_metric": metric,
                "proxmox_display_name": name,
            }
        result = template.render(
            states=SimpleNamespace(sensor=sensors),
            state_attr=lambda entity_id, key: attrs.get(entity_id, {}).get(key),
        )
        return yaml.safe_load(result)

    base = [
        {"entity": "sensor.dh_pve_agent_cpu_usage", "name": "CPU"},
        {"entity": "sensor.dh_pve_agent_memory_usage", "name": "RAM"},
        {"entity": "sensor.dh_pve_agent_swap_usage", "name": "Swap"},
    ]
    assert render([]) == base  # uncalibrated host must not spin forever

    sensors = [
        ("sensor.pve_fan1_speed", "37", "speed_percent", "FAN1",
         "digitalhouses_pve_agent"),
        ("sensor.pve_fan3_speed", "0", "speed_percent", "FAN3",
         "digitalhouses_pve_agent"),
        ("sensor.pve_fan1_rpm", "1700", "rpm", "FAN1 RPM",
         "digitalhouses_pve_agent"),
        ("sensor.pve_fan2_speed", "unavailable", "speed_percent", "FAN2",
         "digitalhouses_pve_agent"),
        ("sensor.somebody_else_speed", "45", "speed_percent", "Other", "other"),
    ]
    assert render(sensors) == base + [
        {"entity": "sensor.pve_fan1_speed", "name": "FAN1"},
        {"entity": "sensor.pve_fan3_speed", "name": "FAN3"},
    ]


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
