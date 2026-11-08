"""UPS front-page summary must reflect shutdown readiness, not UPS power alone."""
from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

CARD = Path(__file__).parents[1] / "examples" / "dh_pve_agent_ups_protection_status_card.yaml"


def test_ups_overview_uses_separate_ups_and_shutdown_readiness_inputs():
    raw = CARD.read_text(encoding="utf-8")
    assert "type: custom:mushroom-template-card" in raw
    assert "sensor.dh_pve_agent_ups_status" in raw
    assert "sensor.dh_pve_agent_ups_shutdown_readiness" in raw
    assert "sensor.dh_pve_agent_ups_problems" in raw
    assert "states.sensor" not in raw
    assert "Готовность shutdown не подтверждена" in raw
    assert "Защита PVE не готова" in raw
    assert "Риск аварийного отключения PVE" in raw
    assert "icon_color: >-" in raw


def test_ups_overview_color_and_text_match_operational_and_protection_states():
    if find_spec("yaml") is None or find_spec("jinja2") is None:
        return

    import jinja2
    import yaml

    card = yaml.safe_load(CARD.read_text(encoding="utf-8"))
    assert card["entity"] == "sensor.dh_pve_agent_ups_shutdown_readiness"
    assert card["tap_action"]["action"] == "more-info"

    def render(ups: str, readiness: str, problems: str, issues: list[str]):
        data = {
            "sensor.dh_pve_agent_ups_status": ups,
            "sensor.dh_pve_agent_ups_shutdown_readiness": readiness,
            "sensor.dh_pve_agent_ups_problems": problems,
        }
        results = {}
        env = jinja2.Environment()
        for field in ("primary", "secondary", "icon", "icon_color"):
            template = env.from_string(card[field])
            results[field] = template.render(
                entity=card["entity"],
                states=lambda entity: data.get(entity, "unknown"),
                state_attr=lambda entity, key: issues
                if entity == card["entity"] and key == "issues"
                else None,
            ).strip()
        return results

    broken = render(
        "online", "warning", "0",
        ["shutdown_policy_not_enabled", "nut_role_not_primary",
         "nut_monitor_not_active", "shutdown_disabled"],
    )
    assert broken == {
        "primary": "Защита PVE не готова",
        "secondary": "UPS: online · Замечаний по shutdown: 4",
        "icon": "mdi:shield-alert-outline",
        "icon_color": "orange",
    }

    ready = render("online", "ok", "0", [])
    assert ready["primary"] == "Защита питания в норме"
    assert ready["icon_color"] == "green"

    power_loss = render("on_battery", "ok", "1", [])
    assert power_loss["primary"] == "Питание от батареи UPS"
    assert power_loss["icon_color"] == "orange"

    unprotected_power_loss = render("on_battery", "warning", "1", ["nut_monitor_not_active"])
    assert unprotected_power_loss["primary"] == "Риск аварийного отключения PVE"
    assert unprotected_power_loss["icon_color"] == "red"

    unknown = render("unknown", "skip", "unknown", [])
    assert unknown["primary"] == "Нет данных от UPS"
    assert unknown["icon_color"] == "grey"

    unknown_shutdown = render("online", "skip", "0", [])
    assert unknown_shutdown["primary"] == "Готовность защиты неизвестна"
    assert unknown_shutdown["icon_color"] == "grey"

    bad_ups = render("low_battery", "ok", "1", [])
    assert bad_ups["primary"] == "Аварийное состояние UPS"
    assert bad_ups["icon_color"] == "red"

    bad_ups_problems = render("online", "ok", "2", [])
    assert bad_ups_problems["primary"] == "UPS требует внимания"
    assert bad_ups_problems["icon_color"] == "orange"
