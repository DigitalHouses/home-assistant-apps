"""Update controls: release verification, MQTT commands and UPS safety."""
import io
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.config import MqttConfig
from app.discovery import build_discovery_payload
from app.identity import HostIdentity
from app.mqtt_bridge import MqttBridge, MqttEvents
from app.runtime_settings import RuntimeSettings
from app.topics import build_topics
from app.update_manager import UpdateManager, latest_release, stable_version


def _config():
    from app.config import AppConfig, GeneralConfig
    return AppConfig(
        general=GeneralConfig(instance_id="node_a", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(host="mqtt", port=1883, username="", password="",
                        topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
                        discovery_prefix="homeassistant", keepalive_seconds=60),
    )


def _topics():
    config = _config()
    identity = HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a", hostname="pve", node_name="PVE",
    )
    return build_topics(config.mqtt, identity), identity


def test_discovery_exposes_update_controls_without_new_device():
    topics, identity = _topics()
    components = build_discovery_payload(_config(), identity, version="0.5.47")["components"]
    expected = {
        "check_updates": ("button", "button.dh_pve_agent_check_updates"),
        "update": ("button", "button.dh_pve_agent_update"),
        "update_available": ("binary_sensor", "binary_sensor.dh_pve_agent_update_available"),
        "latest_version": ("sensor", "sensor.dh_pve_agent_latest_version"),
        "update_status": ("sensor", "sensor.dh_pve_agent_update_status"),
    }
    for key, (platform, entity_id) in expected.items():
        assert components[key]["platform"] == platform
        assert components[key]["default_entity_id"] == entity_id
    assert components["check_updates"]["command_topic"] == topics.update_check
    assert components["update"]["command_topic"] == topics.update_install
    assert components["check_updates"]["retain"] is False
    assert components["update"]["retain"] is False
    assert components["update_available"]["state_topic"] == topics.update_state
    assert components["update_available"]["payload_on"] == "ON"
    assert components["update_available"]["payload_off"] == "OFF"


def test_only_press_is_accepted_and_requests_do_not_accumulate():
    topics, _ = _topics()
    events = MqttEvents(topics, RuntimeSettings())
    for topic, event in ((topics.update_check, events.check_updates_requested),
                         (topics.update_install, events.install_update_requested)):
        assert events.handle_message(topic, b"invalid") is False
        assert not event.is_set()
        assert events.handle_message(topic, b"PRESS")
        assert events.handle_message(topic, b"PRESS")
        assert event.is_set()


def test_retained_mutation_commands_are_rejected():
    topics, _ = _topics()
    bridge = object.__new__(MqttBridge)
    MqttEvents.__init__(bridge, topics, RuntimeSettings())
    bridge.log = Mock()
    bridge.wake_requested = Mock()
    for topic in (topics.update_check, topics.update_install, topics.restart_agent):
        message = SimpleNamespace(topic=topic, payload=b"PRESS", retain=True)
        bridge._on_message(None, None, message)
    assert not bridge.check_updates_requested.is_set()
    assert not bridge.install_update_requested.is_set()
    assert not bridge.restart_requested.is_set()


def test_release_filter_requires_published_stable_product_release():
    def release(tag, *, draft=False, prerelease=False, published_at="2026-10-02"):
        return {"tag_name": tag, "draft": draft,
                "prerelease": prerelease, "published_at": published_at}

    releases = [
        release("digitalhouses_plex_agent-v9.0.0"),
        release("digitalhouses_pve_agent-v0.5.49", prerelease=True),
        release("digitalhouses_pve_agent-v0.5.48", draft=True),
        release("digitalhouses_pve_agent-v0.5.46"),
        release("digitalhouses_pve_agent-v0.5.47"),
        release("digitalhouses_pve_agent-v0.5.50-rc.1"),
    ]

    def opener(request, *, timeout):
        return io.BytesIO(json.dumps(releases).encode())

    assert latest_release(opener=opener) == ("digitalhouses_pve_agent-v0.5.47", "0.5.47")
    assert stable_version("0.5.47") > stable_version("0.5.46")
    with pytest.raises(ValueError):
        stable_version("0.5.47-rc.1")


def test_unknown_on_failed_check_never_becomes_false_update_status(tmp_path):
    manager = UpdateManager(tmp_path, "0.5.46")
    manager._checking = False
    manager._check_error = "GitHub unavailable"
    manager._last_check = time.monotonic()
    bridge = Mock()
    bridge.publish_update_state.return_value = True
    manager.tick(bridge)
    payload = bridge.publish_update_state.call_args.args[0]
    assert payload["available"] is None
    assert payload["latest_version"] == "unknown"
    assert payload["status"] == "error"


def test_check_is_nonblocking_and_install_needs_verified_version(tmp_path, monkeypatch):
    manager = UpdateManager(tmp_path, "0.5.46")
    manager._last_check = time.monotonic()
    bridge = Mock()
    bridge.publish_update_state.return_value = True
    manager.tick(bridge, install=True, denial_reason=lambda: None)
    assert bridge.publish_update_state.call_args.args[0]["status"] == "error"
    assert not (tmp_path / "update_request.json").exists()


def test_preflight_exception_fails_closed_without_crashing_agent(tmp_path, monkeypatch):
    manager = UpdateManager(tmp_path, "0.5.48")
    manager.tag, manager.latest, manager.known = (
        "digitalhouses_pve_agent-v0.5.50", "0.5.50", True
    )
    manager._last_check = time.monotonic()
    bridge = Mock()
    bridge.publish_update_state.return_value = True
    started = Mock()
    monkeypatch.setattr(subprocess, "run", started)

    def broken_guard():
        raise TypeError("'bool' object is not callable")

    manager.tick(bridge, install=True, denial_reason=broken_guard)
    payload = bridge.publish_update_state.call_args.args[0]
    assert payload["status"] == "error"
    assert "UPS preflight failed" in payload["error"]
    assert "bool" in payload["error"]
    assert not (tmp_path / "update_request.json").exists()
    started.assert_not_called()


def test_unsafe_ups_denies_install_without_starting_systemd(tmp_path, monkeypatch):
    manager = UpdateManager(tmp_path, "0.5.46")
    manager.tag, manager.latest, manager.known = (
        "digitalhouses_pve_agent-v0.5.47", "0.5.47", True
    )
    manager._last_check = time.monotonic()
    bridge = Mock()
    bridge.publish_update_state.return_value = True
    started = Mock()
    monkeypatch.setattr(subprocess, "run", started)
    manager.tick(bridge, install=True, denial_reason=lambda: "UPS on battery")
    assert bridge.publish_update_state.call_args.args[0]["error"] == "UPS on battery"
    assert not (tmp_path / "update_request.json").exists()
    started.assert_not_called()


def test_launch_is_fixed_systemd_unit_and_records_exact_release(tmp_path, monkeypatch):
    manager = UpdateManager(tmp_path, "0.5.46")
    manager.tag, manager.latest, manager.known = (
        "digitalhouses_pve_agent-v0.5.47", "0.5.47", True
    )
    manager._last_check = time.monotonic()
    called = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(subprocess, "run", called)
    bridge = Mock()
    bridge.publish_update_state.return_value = True
    manager.tick(bridge, install=True, denial_reason=lambda: None)
    request = json.loads((tmp_path / "update_request.json").read_text())
    assert request["tag"] == "digitalhouses_pve_agent-v0.5.47"
    called.assert_called_once()
    assert called.call_args.args[0] == [
        "systemctl", "start", "--no-block", "digitalhouses_pve_agent-update.service"
    ]


def test_completed_install_does_not_mask_a_newer_successful_no_updates_check(tmp_path):
    manager = UpdateManager(tmp_path, "0.5.56")
    manager.worker.save({
        "state": "completed",
        "error": None,
        "updated_at": "2026-10-03T21:11:06+00:00",
    })
    manager._last_check = time.monotonic()
    # Post-install worker result is initially meaningful until a newer check.
    assert manager._payload()["status"] == "completed"
    manager._check_result = ("digitalhouses_pve_agent-v0.5.56", "0.5.56")
    bridge = Mock()
    bridge.publish_update_state.return_value = True

    manager.tick(bridge)
    payload = bridge.publish_update_state.call_args.args[0]
    assert payload["available"] is False
    assert payload["latest_version"] == "0.5.56"
    assert payload["status"] == "idle"
    assert payload["error"] is None
    assert payload["installation_status"] == "completed"
    assert payload["installation_error"] is None
    assert manager.worker.load()["state"] == "completed"

    # After a restart the persisted check timestamp still beats the old worker.
    restarted = UpdateManager(tmp_path, "0.5.56")
    restarted.known = True
    assert restarted._payload()["status"] == "idle"


def test_newer_worker_result_wins_and_check_failures_remain_visible(tmp_path):
    manager = UpdateManager(tmp_path, "0.5.56")
    manager.known = True
    manager.checked = "2026-10-04T00:00:00+00:00"
    manager.latest = "0.5.56"
    manager.worker.save({
        "state": "completed",
        "error": None,
        "updated_at": "2026-10-04T00:01:00+00:00",
    })
    assert manager._payload()["status"] == "completed"

    # A subsequent check failure reports the check error, not installation.
    manager._status = "error"
    manager._status_error = "HTTP Error 500"
    assert manager._payload()["status"] == "error"
    assert manager._payload()["error"] == "HTTP Error 500"

    # A later successful check supersedes even an old failed install,
    # without discarding the installation failure from diagnostics.
    manager.worker.save({
        "state": "error",
        "error": "Install failed",
        "updated_at": "2026-10-04T00:01:00+00:00",
    })
    manager.checked = "2026-10-04T00:02:00+00:00"
    manager._status = "idle"
    manager._status_error = None
    payload = manager._payload()
    assert payload["status"] == "idle"
    assert payload["installation_status"] == "error"
    assert payload["installation_error"] == "Install failed"


def test_updater_discovery_keeps_separate_installation_diagnostics():
    _, identity = _topics()
    components = build_discovery_payload(
        _config(), identity, version="0.5.57",
    )["components"]
    attrs = components["update_status"]["json_attributes_template"]
    assert "installation_status" in attrs
    assert "installation_error" in attrs
    assert "checked_at" in attrs
