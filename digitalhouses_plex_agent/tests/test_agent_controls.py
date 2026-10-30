"""Contract tests for the unified Plex Agent control card."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import io
import json
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent_card import AgentCard
from app.config import load_config
from app.discovery import build_discovery_payload, build_topics
from app.models import BuildInfo
from app.update_manager import UpdateManager, latest_release


class Clock:
    def __init__(self):
        self.t = 0.0

    def mono(self):
        return self.t

    def iso(self):
        return (datetime(2026, 10, 12, tzinfo=timezone.utc)
                + timedelta(seconds=self.t)).isoformat()


def test_card_success_duration_and_five_second_cleanup(tmp_path):
    clock = Clock()
    seen = []
    card = AgentCard(tmp_path / "card.json",
                     lambda data: seen.append(data.copy()) or True,
                     clock=clock.mono, now=clock.iso)
    assert card.begin("refresh")
    assert not card.begin("check")
    clock.t += 7.6
    assert card.finish("refresh")
    assert card.payload()["duration_seconds"] == 7.6
    clock.t += 4.9
    card.tick()
    assert card.state == "success"
    clock.t += 0.2
    card.tick()
    assert card.state == "idle"
    assert [x["state"] for x in seen][-3:] == ["running", "success", "idle"]


def test_card_error_sticks_until_new_command(tmp_path):
    clock = Clock()
    card = AgentCard(tmp_path / "card.json",
                     lambda _: True, clock=clock.mono, now=clock.iso)
    assert card.begin("check")
    assert card.finish("check", error="GitHub unavailable")
    clock.t += 100
    card.tick()
    assert card.state == "error"
    assert card.begin("refresh")
    assert card.error is None


def test_card_restart_survives_process_restart(tmp_path):
    clock = Clock()
    path = tmp_path / "card.json"
    card = AgentCard(path, lambda _: True, clock=clock.mono,
                     now=clock.iso, boot_id=lambda: "same")
    card.begin("restart")
    clock.t += 10
    new_runtime = AgentCard(path, lambda _: True, clock=clock.mono,
                            now=clock.iso, boot_id=lambda: "same")
    assert new_runtime.state == "running"
    new_runtime.finish("restart")
    assert new_runtime.duration_seconds == 10


def test_discovery_exposes_controls_in_existing_mqtt_device(tmp_path):
    conf = tmp_path / "agent.conf"
    conf.write_text("[mqtt]\nhost=mqtt\n")
    config = load_config(conf)
    topics = build_topics(config)
    discovery = build_discovery_payload(
        config, BuildInfo("0.8.0", "digitalhouses_plex_agent-v0.8.0", "abc")
    )
    components = discovery["components"]
    assert components["agent_card"]["default_entity_id"] == "sensor.dh_plex_agent_card"
    assert components["agent_card"]["state_topic"] == topics.agent_card_state
    assert components["check_updates"]["command_topic"] == topics.update_check
    assert components["restart_agent"]["command_topic"] == topics.restart_agent
    assert components["update"]["command_topic"] == topics.update_install
    assert components["update"]["retain"] is False
    assert components["update_available"]["default_entity_id"] == "binary_sensor.dh_plex_agent_update_available"
    assert components["latest_version"]["default_entity_id"] == "sensor.dh_plex_agent_latest_version"
    assert discovery["device"]["identifiers"] == [topics.device_id]


def test_latest_release_only_published_stable_and_right_product():
    releases = [
        {"tag_name": "digitalhouses_plex_agent-v0.8.0", "draft": True, "published_at": "now"},
        {"tag_name": "digitalhouses_pve_agent-v9.0.0", "published_at": "now"},
        {"tag_name": "digitalhouses_plex_agent-v0.8.0-rc.1", "published_at": "now"},
        {"tag_name": "digitalhouses_plex_agent-v0.7.3", "published_at": "now"},
        {"tag_name": "digitalhouses_plex_agent-v0.7.2", "published_at": "now"},
    ]
    result = latest_release(opener=lambda request, timeout: io.BytesIO(json.dumps(releases).encode()))
    assert result == ("digitalhouses_plex_agent-v0.7.3", "0.7.3")


def test_update_check_async_result_and_no_optimistic_update(tmp_path, monkeypatch):
    import time
    from app import update_manager as module
    monkeypatch.setattr(module, "latest_release", lambda: (
        "digitalhouses_plex_agent-v0.7.3", "0.7.3"
    ))
    manager = UpdateManager(tmp_path, "0.7.2")
    assert manager.payload()["available"] is None
    assert manager.start_check(manual=True)
    result = None
    for _ in range(200):
        result = manager.poll()
        if result is not None:
            break
        time.sleep(.002)
    assert result == (True, None)
    assert manager.payload()["available"] is True
    assert manager.payload()["latest_version"] == "0.7.3"


def test_update_install_requires_verified_release(tmp_path):
    manager = UpdateManager(tmp_path, "0.7.2")
    assert manager.begin_install()[0] is False
    assert not (tmp_path / "update-install-request").exists()


def test_ui_has_only_whole_seconds_and_verified_conditional_action():
    yml = (Path(__file__).resolve().parents[1] / "examples/lovelace/plex_agent_card_ru.yaml").read_text()
    assert "? 1000 : 5000" in yml
    assert "/ 1000" in yml
    assert "toFixed(1)" not in yml
    assert "mdi:robot-outline" in yml
    assert "binary_sensor.dh_plex_agent_update_available" in yml
    assert "entity_id: button.dh_plex_agent_update" in yml
    assert "entity_id: button.dh_plex_agent_restart_agent" in yml


def test_install_waits_for_first_worker_heartbeat(tmp_path):
    from app.state_store import StateStore
    manager = UpdateManager(tmp_path, "0.7.2")
    manager.worker = StateStore(tmp_path / "worker.json")
    now = datetime.now(timezone.utc)
    requested = now.isoformat()
    started = (now - timedelta(seconds=1)).isoformat()
    manager.request.save({
        "tag": "digitalhouses_plex_agent-v0.8.0",
        "version": "0.8.0",
        "requested_at": requested,
    })
    assert manager.install_outcome(started_at=started) is None
    manager.worker.save({"state": "downloading", "updated_at": requested})
    assert manager.install_outcome(started_at=started) is None
    manager.worker.save({"state": "completed", "updated_at": now.isoformat()})
    assert manager.install_outcome(started_at=started)[0] is False
    manager.version = "0.8.0"
    assert manager.install_outcome(started_at=started) == (True, None)



def test_gpu_problem_is_persistent_but_never_hijacks_control_operation(tmp_path):
    clock = Clock()
    events = []
    path = tmp_path / "card.json"
    card = AgentCard(path, lambda v: events.append(v.copy()) or True,
                     clock=clock.mono, now=clock.iso, boot_id=lambda: "boot")
    card.set_problem("gpu_error", "Intel GPU: ошибка работы")
    assert card.state == "idle"
    assert card.payload()["state"] == "problem"
    assert card.payload()["problem_message"] == "Intel GPU: ошибка работы"
    before = len(events)
    card.set_problem("gpu_error", "Intel GPU: ошибка работы")
    assert len(events) == before, "unchanged fault must not flood MQTT"

    assert card.begin("refresh")
    assert card.payload()["state"] == "running"
    clock.t += 2
    assert card.finish("refresh")
    assert card.payload()["state"] == "success"
    clock.t += 6
    card.tick()
    assert card.payload()["state"] == "problem"

    restored = AgentCard(path, lambda _: True, clock=clock.mono,
                         now=clock.iso, boot_id=lambda: "boot")
    assert restored.payload()["state"] == "problem"
    restored.set_problem(None, None)
    assert restored.payload()["state"] == "idle"
    assert restored.payload()["problem_message"] is None


def test_problem_card_ui_has_gpu_fault_without_losing_update_controls():
    card = (
        Path(__file__).resolve().parents[1]
        / "examples/lovelace/plex_agent_card_ru.yaml"
    ).read_text()
    dashboard = (
        Path(__file__).resolve().parents[1]
        / "examples/lovelace/plex-dashboard.yaml"
    ).read_text()
    for content in (card, dashboard):
        assert "item.state === 'problem'" in content
        assert "Обнаружена проблема:" in content
        assert "s === 'problem'" in content
        assert "button.dh_plex_agent_restart_agent" in content
    assert "sensor.dh_plex_agent_gpu_driver_status" in dashboard
    assert "Драйвер" in dashboard


def test_approved_pve_style_problem_card_precedes_controls_in_both_examples():
    root = Path(__file__).resolve().parents[1]
    dashboard = (root / "examples/lovelace/plex-dashboard.yaml").read_text()
    standalone = (root / "examples/lovelace/plex_agent_card_ru.yaml").read_text()
    for yaml in (dashboard, standalone):
        problem = yaml.index("entity: sensor.dh_plex_agent_card")
        button = yaml.index("type: custom:button-card")
        assert problem < button, "PVE-style problem card must appear before controls"
        assert "Обнаружено проблем: 1" in yaml
        assert "Проблем не обнаружено" in yaml
        assert "state_attr(entity, 'problem_message')" in yaml
        assert "mdi:alert-circle" in yaml
        assert "mdi:check-circle" in yaml
    assert "primary: Intel GPU · Драйвер" in dashboard
    assert "primary: Intel GPU · Работа" in dashboard
    assert "entity: sensor.dh_plex_agent_gpu_driver_status" in dashboard
    assert "entity: sensor.dh_plex_agent_gpu_status" in dashboard
    assert "type: custom:mushroom-template-card" in dashboard
