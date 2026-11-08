from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "examples" / "dh_pve_agent_dashboard_ru.yaml"


def test_ru_dashboard_presents_fan_percent_as_primary_metric_with_rpm_fallback():
    text = DASHBOARD.read_text(encoding="utf-8")

    assert "fan.entity_id | replace('_rpm', '_speed')" in text
    assert "speed ~ '%" in text
    assert "~ rpm ~ ' RPM'" in text


def test_ru_dashboard_graph_percent_only_and_always_has_base_entities():
    from importlib.util import find_spec
    from types import SimpleNamespace

    text = DASHBOARD.read_text(encoding="utf-8")
    graph_text = text.split("heading: CPU / RAM / Swap / Fans · 24 часа", 1)[1]
    graph_text = graph_text.split("# RPM-only fallback:", 1)[0]
    # Always exercise the zero-dependency contract in the production CI.
    assert "proxmox_metric') == 'speed_percent'" in graph_text
    assert "proxmox_metric') == 'rpm'" not in graph_text
    assert "y_axis" not in graph_text
    assert "lower_bound_secondary" not in graph_text
    assert "{{ ns.items }}" in graph_text
    for entity in (
        "sensor.dh_pve_agent_cpu_usage",
        "sensor.dh_pve_agent_memory_usage",
        "sensor.dh_pve_agent_swap_usage",
    ):
        assert entity in graph_text

    # The agent itself does not depend on Home Assistant's Jinja/YAML libs.
    # When available in DEV, additionally execute the complete template.
    if find_spec("jinja2") is None or find_spec("yaml") is None:
        return
    import jinja2
    import yaml

    sections = yaml.safe_load(text)["sections"]
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


def test_ru_dashboard_rpm_fallback_only_for_fans_without_numeric_percent():
    from types import SimpleNamespace
    from importlib.util import find_spec

    dashboard = DASHBOARD.read_text(encoding="utf-8")
    rpm_block = dashboard.split("# RPM-only fallback:", 1)[1]
    rpm_block = rpm_block.split("heading: Частота CPU · 24 часа", 1)[0]
    assert "type: custom:auto-entities" in rpm_block
    assert "show_empty: false" in rpm_block
    assert "card_param: cards" in rpm_block
    assert "proxmox_metric') == 'rpm'" in rpm_block
    assert "percent_id = fan.entity_id | replace('_rpm', '_speed')" in rpm_block
    assert "not (states(percent_id) | is_number)" in rpm_block
    assert "fan.state | is_number" in rpm_block
    assert "ns.items | count > 0" in rpm_block
    assert "'lower_bound': 0" in rpm_block
    assert "upper_bound" not in rpm_block
    assert "y_axis" not in rpm_block
    assert "{{ [] }}" in rpm_block
    assert "| tojson" in rpm_block

    # Additional executable rendering checks when optional DEV dependencies
    # are present; production CI remains dependency-free.
    if find_spec("jinja2") is None or find_spec("yaml") is None:
        return

    import jinja2
    import yaml

    dashboard_yaml = yaml.safe_load(dashboard)
    charts = [
        c for section in dashboard_yaml["sections"] for c in section["cards"]
        if c.get("type") == "custom:auto-entities"
        and "RPM (без калибровки)" in c.get("filter", {}).get("template", "")
    ]
    assert len(charts) == 1
    chart = charts[0]
    assert chart["card"] == {"type": "grid", "columns": 1, "square": False}
    assert chart["card_param"] == "cards"
    template = jinja2.Environment().from_string(chart["filter"]["template"])

    def number(value):
        try:
            return float(value) == float(value)
        except (ValueError, TypeError):
            return False

    template.environment.filters["is_number"] = number

    class FakeStates:
        def __init__(self, sensors, by_id):
            self.sensor = sensors
            self.by_id = by_id

        def __call__(self, entity):
            return self.by_id.get(entity, "unknown")

    def render(items):
        sensors, attrs, states_by_id = [], {}, {}
        for entity, state, metric, name, integration in items:
            sensors.append(SimpleNamespace(entity_id=entity, state=state, name=name))
            states_by_id[entity] = state
            attrs[entity] = {
                "proxmox_integration": integration,
                "proxmox_section": "cooling",
                "proxmox_metric": metric,
                "proxmox_display_name": name,
            }
        result = template.render(
            states=FakeStates(sensors, states_by_id),
            state_attr=lambda entity, key: attrs.get(entity, {}).get(key),
        )
        # HA's auto-entities accepts a JSON list of generated cards.
        return yaml.safe_load(result)

    assert render([]) == []  # Never create an empty mini-graph-card.
    rows = [
        ("sensor.pve_fan1_rpm", "1700", "rpm", "FAN1", "digitalhouses_pve_agent"),
        ("sensor.pve_fan3_rpm", "0", "rpm", "FAN3", "digitalhouses_pve_agent"),
        ("sensor.pve_fan2_rpm", "2200", "rpm", "FAN2", "digitalhouses_pve_agent"),
        ("sensor.pve_fan2_speed", "62", "speed_percent", "FAN2", "digitalhouses_pve_agent"),
        ("sensor.pve_fan9_rpm", "unavailable", "rpm", "FAN9", "digitalhouses_pve_agent"),
        ("sensor.elsewhere_fan_rpm", "2700", "rpm", "Other", "elsewhere"),
    ]
    cards = render(rows)
    assert len(cards) == 1
    graph = cards[0]
    assert graph["type"] == "custom:mini-graph-card"
    assert graph["hours_to_show"] == 24
    assert graph["decimals"] == 0
    assert graph["lower_bound"] == 0
    assert "upper_bound" not in graph
    assert graph["entities"] == [
        {"entity": "sensor.pve_fan1_rpm", "name": "FAN1"},
        {"entity": "sensor.pve_fan3_rpm", "name": "FAN3"},
    ]
    # Once percentages become numeric, the RPM fallback is removed.
    for fan in ("fan1", "fan3"):
        rows.append((f"sensor.pve_{fan}_speed", "0", "speed_percent", fan, "digitalhouses_pve_agent"))
    assert render(rows) == []
