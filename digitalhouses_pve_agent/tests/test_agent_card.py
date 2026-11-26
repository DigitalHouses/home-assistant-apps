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
        lambda payload: published.append(payload.copy()) or True,
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
    card = AgentCard(lambda p: True, clock=clock.mono, now=clock.iso)
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
    card = AgentCard(lambda p: seen.append(p.copy()) or True,
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


def test_ru_dashboard_has_problems_and_four_lightweight_status_cards():
    from pathlib import Path
    yaml = (Path(__file__).parents[1] / "examples" /
            "dh_pve_agent_dashboard_ru.yaml").read_text()
    assert "primary: Problems" in yaml
    for name in ("Updates", "Refresh", "Restart"):
        assert f"primary: {name}" in yaml
    assert "type: custom:button-card" not in yaml.split("heading: Хост", 1)[0]
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


def test_updates_card_visible_for_verified_new_release_or_active_install():
    from pathlib import Path
    root = Path(__file__).parents[1]
    for path in (root / "examples/dh_pve_agent_card_ru.yaml",
                 root / "examples/dh_pve_agent_dashboard_ru.yaml"):
        source = path.read_text()
        assert "binary_sensor.dh_pve_agent_update_available" in source
        assert "primary: Updates" in source
        assert "state: [install, check]" in source
        assert "attribute: operation" in source
        assert "v{{ states('sensor.dh_pve_agent_version') }}" in source
        assert "v{{ states('sensor.dh_pve_agent_latest_version') }}" in source
        assert "Обновление версии" in source
        assert "content: Новая версия" in source
        assert "performance.now()" not in source


def test_status_cards_use_native_ha_relative_time_without_javascript_timer():
    from pathlib import Path
    root = Path(__file__).parents[1]
    for path in (root / "examples/dh_pve_agent_card_ru.yaml",
                 root / "examples/dh_pve_agent_dashboard_ru.yaml"):
        source = path.read_text()
        assert "time_since(as_datetime(start))" in source
        assert "performance.now()" not in source
        assert "this._dh_pve_timer" not in source
        assert "update_timer" not in source


def test_user_commands_are_acknowledged_before_blocking_background_work():
    """MQTT check/install request must publish running before background work.

    No new acknowledgement entity: the existing app-owned card remains the
    authoritative source of truth. This ordering protects the first visible
    state transition against a slow diagnostics sweep.
    """
    from pathlib import Path

    main = (Path(__file__).parents[1] / "app" / "main.py").read_text()
    loop = main[main.index("        while not stop_event.is_set():"):]
    assert loop.count('card.begin("check")') == 1
    assert loop.count('card.begin("install")') == 1
    assert loop.count("update_manager.tick(") == 1
    assert loop.index('card.begin("check")') < loop.index("runtime.process_events()")
    assert loop.index('card.begin("install")') < loop.index("runtime.process_events()")
    assert loop.index("update_manager.tick(") < loop.index("runtime.tick(time.monotonic())")
    assert loop.index("card.tick()") < loop.index("ups_runtime.tick(time.monotonic())")
    assert loop.index('card.begin("restart")') < loop.index('card.begin("check")')
    # During foreground update/install the existing mutually exclusive
    # commands must be suppressed; never launch an unrelated refresh.
    assert 'if card.state == "running" and card.operation in {"check", "install"}:' in loop
    assert "bridge.refresh_requested.clear()" in loop


def test_status_cards_are_reused_in_dashboard_and_controls_preserved():
    from pathlib import Path
    root = Path(__file__).parents[1]
    fragment = (root / "examples/dh_pve_agent_status_cards_ru.yaml").read_text()
    standalone = (root / "examples/dh_pve_agent_card_ru.yaml").read_text()
    dashboard = (root / "examples/dh_pve_agent_dashboard_ru.yaml").read_text()
    assert "type: vertical-stack\ncards:\n" in standalone
    assert standalone.endswith(fragment.split("cards:\n", 1)[1])
    assert "primary: Problems" in dashboard
    for title in ("Updates", "Refresh", "Restart"):
        assert f"primary: {title}" in dashboard
    assert dashboard.count("entity_id: button.dh_pve_agent_refresh") == 1
    assert "content: Версия" in dashboard
    assert "content: Новая версия" in dashboard
    assert "content: Перезапуск" in dashboard




def test_new_process_starts_clean_without_reading_old_ui_checkpoint(tmp_path):
    old = tmp_path / "agent_card.json"
    old.write_text('{"state":"error","operation":"install","error":"No matching installation transaction"}')
    card = AgentCard(lambda _: True)
    assert card.state == "idle" and card.error is None
    assert card.last_collection_at is None
    for operation in ("refresh", "check", "install", "restart"):
        assert card.begin(operation)
        card = AgentCard(lambda _: True)
        assert card.state == "idle" and card.operation is None
    assert old.exists()  # no migration or cleanup necessary


def test_successful_cli_update_with_reversed_or_missing_timestamps(tmp_path):
    from app.update_manager import UpdateManager
    manager = UpdateManager(tmp_path, "0.5.104")
    manager.request.save({"version": "0.5.104", "requested_at": "2026-11-25T19:42:38.818226+00:00"})
    manager.worker.save({"state": "completed", "error": None, "updated_at": "2026-11-25T19:43:00.818212+00:00"})
    card = AgentCard(lambda _: True, now=lambda: "2026-11-25T19:42:41.329736+00:00")
    manager.sync_install_card(card, startup=True)
    assert card.state == "idle" and card.error is None
    manager.request.path.unlink()
    manager.sync_install_card(card, startup=True)
    assert card.state == "idle" and card.error is None


def test_surviving_worker_is_observed_without_reconstructing_ui_transaction(tmp_path):
    from app.update_manager import UpdateManager
    manager = UpdateManager(tmp_path, "0.5.105")
    manager.worker.save({"state": "verifying"})
    card = AgentCard(lambda _: True)
    manager.sync_install_card(card, startup=True)
    assert card.state == "running" and card.operation == "install"
    assert card.started_at is None
    manager.worker.save({"state": "completed"})
    manager.sync_install_card(card)
    assert card.state == "success" and card.duration_seconds is None
    assert card.error is None


def test_real_update_failure_preserved_and_superseded_error_cleared(tmp_path):
    from app.update_manager import UpdateManager
    manager = UpdateManager(tmp_path, "0.5.104")
    manager.request.save({"version": "0.5.105"})
    manager.worker.save({"state": "error", "error": "Rollback completed"})
    card = AgentCard(lambda _: True)
    manager.sync_install_card(card, startup=True)
    assert card.state == "error" and card.error == "Rollback completed"
    manager.version = "0.5.105"
    card = AgentCard(lambda _: True)
    manager.sync_install_card(card, startup=True)
    assert card.state == "idle" and card.error is None


def test_denied_install_does_not_use_old_worker_success(tmp_path):
    from app.update_manager import UpdateManager
    manager = UpdateManager(tmp_path, "0.5.104")
    manager.worker.save({"state": "completed"})
    card = AgentCard(lambda _: True)
    card.begin("install")
    manager._status, manager._status_error = "error", "UPS on battery"
    manager.sync_install_card(card, requested=True)
    assert card.state == "error" and card.error == "UPS on battery"


def test_missing_worker_state_clears_ui_without_fake_failure_or_success(tmp_path):
    from app.update_manager import UpdateManager
    manager = UpdateManager(tmp_path, "0.5.104")
    card = AgentCard(lambda _: True)
    card.begin("install")
    manager.sync_install_card(card)
    assert card.state == "idle" and card.error is None


def test_main_uses_current_worker_and_no_persisted_card():
    from pathlib import Path
    main = (Path(__file__).parents[1] / "app/main.py").read_text()
    assert "agent_card.json" not in main
    assert "install_card_outcome" not in main
    assert "update_manager.sync_install_card(card, startup=True)" in main
    assert "update_manager.sync_install_card(card, requested=install_update)" in main
