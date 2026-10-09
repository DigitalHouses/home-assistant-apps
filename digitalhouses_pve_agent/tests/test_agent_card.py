from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.agent_card import AgentCard


class Clock:
    def __init__(self):
        self.seconds = 0.0
        self.origin = datetime(2026, 10, 9, tzinfo=timezone.utc)

    def mono(self):
        return self.seconds

    def iso(self):
        return (self.origin + timedelta(seconds=self.seconds)).isoformat()

    def advance(self, sec):
        self.seconds += sec


def test_user_operation_runs_finishes_and_clears_after_five_seconds(tmp_path):
    clock = Clock()
    published = []
    card = AgentCard(
        tmp_path / "card.json", lambda payload: published.append(payload.copy()) or True,
        clock=clock.mono, now=clock.iso,
    )
    assert card.begin("refresh")
    assert published[-1]["state"] == "running"
    assert card.begin("refresh") is False
    clock.advance(12.44)
    assert card.finish("refresh")
    assert card.payload()["duration_seconds"] == 12.44
    assert card.payload()["state"] == "success"
    clock.advance(4.9)
    card.tick()
    assert card.payload()["state"] == "success"
    clock.advance(0.2)
    card.tick()
    assert card.payload()["state"] == "idle"
    assert card.payload()["operation"] is None


def test_error_remains_until_next_operation(tmp_path):
    clock = Clock()
    card = AgentCard(tmp_path / "card.json", lambda p: True, clock=clock.mono, now=clock.iso)
    card.begin("check")
    clock.advance(1.7)
    card.finish("check", error="GitHub unavailable")
    clock.advance(500)
    card.tick()
    assert card.state == "error"
    assert card.error == "GitHub unavailable"
    assert card.begin("restart")
    assert card.error is None


def test_background_collection_updates_freshness_not_foreground(tmp_path):
    clock = Clock()
    seen = []
    card = AgentCard(tmp_path / "card.json", lambda p: seen.append(p.copy()) or True,
                     clock=clock.mono, now=clock.iso)
    card.collected(clock.iso())
    assert seen[-1]["last_collection_at"] == clock.iso()
    assert card.state == "idle"
    clock.advance(10)
    card.collected(clock.iso())
    assert len(seen) == 1
    clock.advance(21)
    card.collected(clock.iso())
    assert len(seen) == 2
    assert card.state == "idle"


def test_restart_handoff_requires_new_runtime_confirmation(tmp_path):
    clock = Clock()
    path = tmp_path / "card.json"
    card = AgentCard(path, lambda p: True, clock=clock.mono, now=clock.iso)
    card.begin("restart")
    clock.advance(6.2)
    recovered = AgentCard(path, lambda p: True, clock=clock.mono, now=clock.iso)
    assert recovered.state == "running"
    assert recovered.finish("restart")
    assert recovered.state == "success"
    assert recovered.duration_seconds == 6.2


def test_interrupted_refresh_is_not_marked_success(tmp_path):
    clock = Clock()
    path = tmp_path / "card.json"
    card = AgentCard(path, lambda p: True, clock=clock.mono, now=clock.iso)
    card.begin("refresh")
    clock.advance(5)
    recovered = AgentCard(path, lambda p: True, clock=clock.mono, now=clock.iso)
    assert recovered.state == "error"


def test_discovery_card_is_same_mqtt_device():
    from app.config import AppConfig, GeneralConfig, MqttConfig
    from app.identity import HostIdentity
    from app.discovery import build_discovery_payload
    config = AppConfig(
        general=GeneralConfig(instance_id="node_a", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(host="mqtt", port=1883, username="", password="",
                        topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
                        discovery_prefix="homeassistant", keepalive_seconds=60),
    )
    identity = HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a", hostname="pve", node_name="PVE",
    )
    components = build_discovery_payload(config, identity, version="0.5.59")["components"]
    card = components["agent_card"]
    assert card["default_entity_id"] == "sensor.dh_pve_agent_card"
    assert card["state_topic"].endswith("/agent/card")
    assert "last_collection_at" in card["json_attributes_template"]


def test_ru_dashboard_has_problem_card_then_unified_agent_card():
    from pathlib import Path
    yaml = (Path(__file__).parents[1] / "examples" /
            "dh_pve_agent_dashboard_ru.yaml").read_text()
    problems = yaml.index("entity: sensor.dh_pve_agent_problems")
    agent = yaml.index("type: custom:button-card")
    assert problems < agent
    assert yaml.count("heading: Приложение") == 0
    assert "content: Новая версия" in yaml
    assert "content: Обновить" in yaml
    assert "content: Версия" in yaml
    assert "content: Перезапуск" in yaml
    assert yaml.count("entity_id: button.dh_pve_agent_refresh") == 1


def test_github_check_duration_is_product_owned_and_persisted(tmp_path, monkeypatch):
    import time
    import app.update_manager as module
    from app.update_manager import UpdateManager

    monkeypatch.setattr(module, 'latest_release', lambda: (
        'digitalhouses_pve_agent-v0.5.59', '0.5.59'
    ))
    manager = UpdateManager(tmp_path, '0.5.59')
    assert manager.start_check()
    # The background worker completes even without a Home Assistant browser.
    for _ in range(200):
        if not manager._checking:
            break
        time.sleep(0.002)
    manager._apply_check()
    payload = manager._payload()
    assert payload['status'] == 'idle'
    assert payload['check_started_at']
    assert isinstance(payload['check_duration_seconds'], float)
    assert payload['check_duration_seconds'] >= 0
    cached = manager.cache.load()
    assert cached['check_started_at'] == payload['check_started_at']
    assert cached['check_duration_seconds'] == payload['check_duration_seconds']


def test_compact_card_keeps_verified_update_visible_after_operation_result():
    """Update alert is persistent only for verified availability, not guessed."""
    from pathlib import Path
    root = Path(__file__).parents[1]
    standalone = (root / "examples/dh_pve_agent_card_ru.yaml").read_text()
    dashboard = (root / "examples/dh_pve_agent_dashboard_ru.yaml").read_text()

    for yaml in (standalone, dashboard):
        assert "states['binary_sensor.dh_pve_agent_update_available']?.state === 'on'" in yaml
        assert "states['sensor.dh_pve_agent_latest_version']?.state" in yaml
        assert "' → v' + latest" in yaml
        assert "'Доступна новая версия'" in yaml
        assert "upgrade ? 'mdi:package-up'" in yaml
        assert "upgrade ? 'var(--warning-color, orange)'" in yaml
        assert "content: Новая версия" in yaml
        # Running, error and five-second result always win over persistent alert.
        assert yaml.index("if (item.state === 'running')") < yaml.index("if (item.state === 'error')")
        assert yaml.index("if (item.state === 'error')") < yaml.index("if (item.state === 'success')")
        assert yaml.index("if (item.state === 'success')") < yaml.index(
            "// A verified new release stays visible after the five-second result."
        )
        assert yaml.index("// A verified new release stays visible") < yaml.index(
            "const ts = Date.parse(a.last_collection_at || '');"
        )
