"""Four low-cost HA status cards: Problems, Updates, Refresh and Restart."""
from __future__ import annotations

from pathlib import Path
from importlib.util import find_spec
from datetime import datetime, timezone

ROOT = Path(__file__).parents[1]
FRAGMENT = ROOT / "examples" / "dh_pve_agent_status_cards_ru.yaml"
DASHBOARD = ROOT / "examples" / "dh_pve_agent_dashboard_ru.yaml"


def _cards():
    import yaml
    return yaml.safe_load(FRAGMENT.read_text(encoding="utf-8"))["cards"]


def test_four_status_cards_no_browser_poller_and_no_new_entities():
    text = FRAGMENT.read_text(encoding="utf-8")
    dashboard = DASHBOARD.read_text(encoding="utf-8")
    assert "custom:button-card" not in dashboard.split("heading: Хост", 1)[0]
    for forbidden in ("update_timer", "performance.now()", "this._dh_pve_timer",
                      "setInterval(", "states.sensor |"):
        assert forbidden not in text
    for entity in ("sensor.dh_pve_agent_card", "sensor.dh_pve_agent_problems",
                   "sensor.dh_pve_agent_ups_shutdown_readiness",
                   "sensor.dh_pve_agent_ups_status"):
        assert entity in text
    assert "release_published_at" not in text
    assert "time_since(as_datetime(start))" in text
    assert text.count("type: custom:mushroom-template-card") == 4
    assert text.count("type: conditional") == 4  # 3 cards and 1 chip
    assert text.count("state: running") == 3
    assert "sensor.dh_pve_agent_update_status" in text
    assert "digitalhouses_pve_agent" in text


def test_four_cards_match_dashboard_without_extra_layout_wrappers():
    if find_spec("yaml") is None:
        return
    import yaml
    fragment = _cards()
    full = yaml.safe_load(DASHBOARD.read_text())["sections"][0]["cards"]
    assert fragment == full[1:6]
    assert len(fragment) == 5
    assert [c.get("card", {}).get("primary") for c in fragment[1:4]] == [
        "Updates", "Refresh", "Restart"
    ]
    assert fragment[0]["primary"] == "Problems"
    assert all(c["grid_options"]["columns"] == 12 for c in fragment)
    assert [c["type"] for c in fragment[:4]] == [
        "custom:mushroom-template-card", "conditional", "conditional", "conditional"
    ]
    assert all(c["card"]["type"] == "custom:mushroom-template-card" for c in fragment[1:4])
    assert fragment[4]["type"] == "custom:mushroom-chips-card"
    assert [c["chips"][0]["content"] for c in fragment[4:5]] == ["Обновить"]


def test_conditional_visibility_tracks_operations_without_timers():
    if find_spec("yaml") is None:
        return
    updates, refresh, restart = _cards()[1:4]
    conditions = updates["conditions"]
    assert conditions[0]["condition"] == "or"
    assert conditions[0]["conditions"][0]["entity"] == "binary_sensor.dh_pve_agent_update_available"
    assert conditions[0]["conditions"][0]["state"] == "on"
    install_branch = conditions[0]["conditions"][1]["conditions"]
    assert install_branch[0]["state"] == "running"
    assert install_branch[1]["attribute"] == "operation"
    assert install_branch[1]["state"] == ["install", "check"]
    for card, operation in ((refresh, "refresh"), (restart, "restart")):
        assert card["conditions"][0]["state"] == "running"
        assert card["conditions"][1]["attribute"] == "operation"
        assert card["conditions"][1]["state"] == operation


def test_problems_fallback_and_remedies():
    if find_spec("yaml") is None or find_spec("jinja2") is None:
        return
    import jinja2
    problems = _cards()[0]
    env = jinja2.Environment()
    template = env.from_string(problems["secondary"])

    def render(agent="idle", active=None, readiness="ok", issues=None, ups="online",
               ups_available="on", update="idle", refresh="idle", pve="0"):
        states_map = {
            "sensor.dh_pve_agent_card": agent,
            "sensor.dh_pve_agent_problems": pve,
            "sensor.dh_pve_agent_ups_shutdown_readiness": readiness,
            "sensor.dh_pve_agent_ups_status": ups,
            "sensor.dh_pve_agent_ups_problems": "0",
            "binary_sensor.dh_pve_agent_ups_available": ups_available,
            "binary_sensor.dh_pve_agent_smart_collector": "on",
            "sensor.dh_pve_agent_update_status": update,
            "sensor.dh_pve_agent_refresh_state": refresh,
        }
        attrs_map = {
            ("sensor.dh_pve_agent_problems", "active"): active or [],
            ("sensor.dh_pve_agent_ups_shutdown_readiness", "issues"): issues or [],
            ("sensor.dh_pve_agent_card", "operation"): "refresh",
            ("sensor.dh_pve_agent_card", "error"): "QGA timeout",
        }
        return template.render(
            entity="sensor.dh_pve_agent_card",
            states=lambda e: states_map.get(e, "unknown"),
            state_attr=lambda e, k: attrs_map.get((e, k)),
        )

    good = render()
    assert "Проблем не обнаружено" in good
    offline = render(agent="unavailable")
    assert "PVE Agent offline" in offline and "проверьте службу" in offline
    assert "Проблем не обнаружено" not in offline

    four = render(readiness="warning", issues=[
        "shutdown_policy_not_enabled", "nut_role_not_primary",
        "nut_monitor_not_active", "shutdown_disabled",
    ])
    for i in range(1, 5):
        assert f"{i}." in four
    assert "NUT PRIMARY" in four and "nut-monitor" in four
    assert "активируйте команду shutdown" in four

    disk = render(pve="1", active=[{
        "category": "disk", "metric": "health",
        "object_name": "HDD", "summary": "SMART error"
    }])
    assert "Проверьте SMART" in disk and "SMART error" in disk

    battery = render(ups="low_battery")
    assert "низкий заряд" in battery
    operation = render(agent="error")
    assert "QGA timeout" in operation and "журнал PVE Agent" in operation


def test_time_since_uses_native_ha_template_function_only_for_running_cards():
    if find_spec("yaml") is None or find_spec("jinja2") is None:
        return
    import jinja2
    updates, refresh, restart = _cards()[1:4]
    env = jinja2.Environment()
    start = "2026-11-09T07:00:00+05:00"

    def render(card, operation, state="running"):
        return env.from_string(card["card"]["secondary"]).render(
            entity="sensor.dh_pve_agent_card",
            states=lambda e: state if e=="sensor.dh_pve_agent_card" else (
                "0.5.78" if e=="sensor.dh_pve_agent_version" else "0.5.79"
            ),
            state_attr=lambda e, key: operation if key=="operation" else start,
            as_datetime=lambda s: datetime.fromisoformat(s),
            time_since=lambda dt: "5 секунд",
        )

    assert "Обновление версии" in render(updates, "install")
    assert "Проверка версии" in render(updates, "check")
    assert "5 секунд назад" in render(updates, "install")
    assert "v0.5.78" in render(updates, "idle", state="idle")
    assert "v0.5.79" in render(updates, "idle", state="idle")
    assert "5 секунд назад" in render(refresh, "refresh")
    assert "5 секунд назад" in render(restart, "restart")
