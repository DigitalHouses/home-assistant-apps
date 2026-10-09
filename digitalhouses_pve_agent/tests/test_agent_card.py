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


def test_restart_duration_ignores_wall_clock_skew_between_processes(tmp_path):
    """A two-second clock correction must not shorten a restarted operation."""
    clock = Clock()
    path = tmp_path / "card.json"
    boot = lambda: "same-pve-boot"
    first = AgentCard(path, lambda _: True, clock=clock.mono, now=clock.iso,
                      boot_id=boot)
    first.begin("restart")
    clock.advance(10)
    # The host wall clock moved backward by two seconds while restarting.
    skewed_wall = lambda: (
        clock.origin + timedelta(seconds=clock.seconds - 2)
    ).isoformat()
    second = AgentCard(path, lambda _: True, clock=clock.mono, now=skewed_wall,
                       boot_id=boot)
    assert second.state == "running"
    assert second._started_monotonic == 0.0
    assert second.finish("restart")
    assert second.duration_seconds == 10.0  # old implementation: 8.0
    assert "_started_monotonic" not in second.payload()
    assert "_start_boot_id" not in second.payload()


def test_install_cross_process_uses_monotonic_and_falls_back_across_host_reboot(tmp_path):
    clock = Clock()
    path = tmp_path / "card.json"
    origin = AgentCard(path, lambda _: True, clock=clock.mono, now=clock.iso,
                       boot_id=lambda: "old-boot")
    origin.begin("install")
    clock.advance(8)
    # Different PVE boot ID means the monotonic tick has lost its origin.
    new_boot = AgentCard(
        path, lambda _: True, clock=lambda: 1.0, now=clock.iso,
        boot_id=lambda: "new-boot",
    )
    assert new_boot.state == "running"
    assert new_boot._started_monotonic is None
    assert new_boot.finish("install")
    assert new_boot.duration_seconds == 8.0


def test_compact_timer_uses_local_browser_monotonic_clock_not_pve_wall_clock():
    from pathlib import Path
    root = Path(__file__).parents[1]
    for path in [
        root / "examples/dh_pve_agent_card_ru.yaml",
        root / "examples/dh_pve_agent_dashboard_ru.yaml",
    ]:
        source = path.read_text()
        assert "performance.now()" in source
        assert "this._dh_pve_timer" in source
        assert "Date.now() - start" not in source
        assert "Math.floor((performance.now() - since) / 100)" in source
        assert "Ожидание запуска агента…" in source

def test_installer_finishes_after_new_agent_started_and_automatic_check(tmp_path):
    """A newer successful GitHub check must not conceal worker completion."""
    from datetime import datetime, timedelta, timezone
    from app.update_manager import UpdateManager
    from app.agent_card import AgentCard

    base = datetime(2026, 10, 9, 17, 0, tzinfo=timezone.utc)
    instant = lambda delta: (base + timedelta(seconds=delta)).isoformat()
    card_clock = Clock()
    old = AgentCard(tmp_path / "agent_card.json", lambda _: True,
                    clock=card_clock.mono, now=card_clock.iso,
                    boot_id=lambda: "pve-boot")
    assert old.begin("install")
    # Align the test card with the updater transaction timeline.
    old.started_at = instant(0)
    old._persist()
    updater = UpdateManager(tmp_path, "0.5.62")
    updater.request.save({"version": "0.5.62", "requested_at": instant(1)})
    updater.worker.save({"state": "verifying", "updated_at": instant(3)})
    card_clock.advance(10)
    recovered = AgentCard(tmp_path / "agent_card.json", lambda _: True,
                          clock=card_clock.mono, now=card_clock.iso,
                          boot_id=lambda: "pve-boot")
    assert recovered.state == "running"
    assert recovered.operation == "install"
    assert updater.install_card_outcome(card_started_at=instant(0)) is None

    updater.worker.save({"state": "completed", "updated_at": instant(13)})
    # The aggregate status is IDLE after a fresher automatic GitHub check.
    updater.known = True
    updater.latest = "0.5.62"
    updater.checked = instant(14)
    assert updater._payload()["status"] == "idle"
    assert updater.install_card_outcome(card_started_at=recovered.started_at) == (True, None)
    assert recovered.finish("install")
    assert recovered.state == "success"
    assert recovered.duration_seconds == 10.0


def test_install_card_reports_worker_error_after_restart(tmp_path):
    from datetime import datetime, timedelta, timezone
    from app.update_manager import UpdateManager

    now = datetime(2026, 10, 9, 17, tzinfo=timezone.utc)
    ts = lambda delta: (now + timedelta(seconds=delta)).isoformat()
    updater = UpdateManager(tmp_path, "0.5.61")
    updater.request.save({"version": "0.5.62", "requested_at": ts(1)})
    updater.worker.save({"state": "error", "error": "Rollback completed",
                        "updated_at": ts(12)})
    updater.known = True
    updater.latest = "0.5.62"
    updater.checked = ts(14)  # masks old worker's terminal status
    assert updater._payload()["status"] == "idle"
    assert updater.install_card_outcome(card_started_at=ts(0)) == (
        False, "Rollback completed"
    )


def test_install_card_does_not_accept_stale_worker_or_wrong_version(tmp_path):
    from datetime import datetime, timedelta, timezone
    from app.update_manager import UpdateManager

    base = datetime(2026, 10, 9, 17, tzinfo=timezone.utc)
    ts = lambda secs: (base + timedelta(seconds=secs)).isoformat()
    updater = UpdateManager(tmp_path, "0.5.61")
    updater.request.save({"version": "0.5.62", "requested_at": ts(1)})
    updater.worker.save({"state": "completed", "updated_at": ts(12)})
    result = updater.install_card_outcome(card_started_at=ts(0))
    assert result[0] is False
    assert "does not match" in result[1]
    # A later manual upgrade may move beyond the originally requested version.
    updater.version = "0.5.63"
    assert updater.install_card_outcome(card_started_at=ts(0)) == (True, None)
    # A stale transaction must still be rejected even if the version is newer.
    assert updater.install_card_outcome(card_started_at=ts(13)) is None
    updater.worker.save({"state": "error", "error": "Old error",
                        "updated_at": ts(0)})
    assert updater.install_card_outcome(card_started_at=ts(0)) is None


def test_install_card_denied_by_ups_does_not_report_previous_success(tmp_path):
    from datetime import datetime, timedelta, timezone
    from app.update_manager import UpdateManager

    base = datetime(2026, 10, 9, 17, tzinfo=timezone.utc)
    ts = lambda secs: (base + timedelta(seconds=secs)).isoformat()
    updater = UpdateManager(tmp_path, "0.5.62")
    updater.request.save({"version": "0.5.62", "requested_at": ts(-20)})
    updater.worker.save({"state": "completed", "updated_at": ts(-5)})
    updater._status, updater._status_error = "error", "UPS on battery"
    assert updater.install_card_outcome(card_started_at=ts(0)) == (
        False, "UPS on battery"
    )


def test_main_install_completion_uses_transaction_not_aggregated_status():
    from pathlib import Path
    source = (Path(__file__).parents[1] / "app/main.py").read_text()
    assert "update_manager.install_card_outcome(" in source
    assert 'card.finish("install", error=str(result.get("error")' not in source
