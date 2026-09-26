import dataclasses
import inspect
import queue
import subprocess
import threading
from types import SimpleNamespace

import pytest

import app.ups_control as ups_control
from app.config import MqttConfig, UpsConfig
from app.discovery_ups import build_ups_discovery_payload
from app.discovery_ups_groups import route_ups_discovery_groups
from app.identity import HostIdentity
from app.mqtt_bridge import MqttEvents
from app.runtime_settings import RuntimeSettings
from app.state_store import StateStore
from app.topics import build_topics, build_ups_topics
from app.ups_control import parse_upscmd_list_output
from app.ups_nut import parse_upsc_output
from app.ups_runtime import UpsRuntime


def _mqtt():
    return MqttConfig(
        host="mqtt",
        port=1883,
        username="",
        password="",
        topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
        discovery_prefix="homeassistant",
        keepalive_seconds=60,
    )


def _identity():
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )


def _ups_config():
    return UpsConfig(
        enabled=True,
        name="ups",
        host="127.0.0.1",
        port=3493,
        poll_interval_seconds=5.0,
        command_timeout_seconds=3.0,
        command_username="digitalhouses_pve_agent",
        command_password="super-secret",
    )


def _beeper_caps():
    return parse_upscmd_list_output(
        "beeper.off - Disable beeper\n"
        "beeper.on - Enable beeper\n"
    )


def test_beeper_capability_selects_safe_on_off_commands():
    caps = parse_upscmd_list_output(
        "beeper.disable - Disable beeper\n"
        "beeper.enable - Enable beeper\n"
        "beeper.off - Legacy disable\n"
        "beeper.on - Legacy enable\n"
    )

    assert callable(getattr(caps, "beeper_command", None))
    assert caps.beeper_command(True) == "beeper.enable"
    assert caps.beeper_command(False) == "beeper.disable"
    assert caps.supports_beeper_switch() is True

    mute_only = parse_upscmd_list_output("beeper.mute - Mute beeper\n")
    assert mute_only.supports_beeper_switch() is False

    disabled = dataclasses.replace(caps, controls_enabled=False)
    assert disabled.supports_beeper_switch() is False


def test_beeper_executor_allows_only_beeper_on_off_family_and_hides_password():
    executor = getattr(ups_control, "run_ups_beeper_command", None)
    assert callable(executor)
    config = _ups_config()
    calls = []

    def ok_runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="OK\n", stderr="")

    for command_name in (
        "beeper.on",
        "beeper.off",
        "beeper.enable",
        "beeper.disable",
    ):
        executor(config, command_name, runner=ok_runner)
        assert calls[-1][0][-1] == command_name
        assert calls[-1][0][:5] == [
            "upscmd",
            "-u",
            "digitalhouses_pve_agent",
            "-p",
            "super-secret",
        ]
        assert calls[-1][1]["timeout"] == 3.0
        assert calls[-1][1]["check"] is True

    with pytest.raises(ValueError):
        executor(config, "load.off", runner=ok_runner)

    def failing_runner(command, **kwargs):
        raise subprocess.CalledProcessError(
            1,
            command,
            stderr="authentication failed for super-secret",
        )

    with pytest.raises(Exception) as exc_info:
        executor(config, "beeper.off", runner=failing_runner)
    assert "super-secret" not in str(exc_info.value)


def test_mqtt_switch_topic_accepts_only_on_off_payloads():
    ups = build_ups_topics(_mqtt(), _identity())
    assert hasattr(ups, "beeper_set")

    events = MqttEvents(build_topics(_mqtt(), _identity()), RuntimeSettings())
    events.configure_ups(ups)
    updates = getattr(events, "ups_beeper_updates", None)
    assert updates is not None

    assert events.handle_message(ups.beeper_set, b"OFF") is True
    assert updates.get_nowait() is False
    assert events.handle_message(ups.beeper_set, b"ON") is True
    assert updates.get_nowait() is True
    assert events.handle_message(ups.beeper_set, b"INVALID") is False


def test_discovery_exposes_feedback_backed_beeper_switch_only_when_supported():
    mqtt = _mqtt()
    identity = _identity()
    ups_topics = build_ups_topics(mqtt, identity)
    snapshot = parse_upsc_output("ups.status: OL\nups.beeper.status: enabled\n")

    payload = build_ups_discovery_payload(
        mqtt,
        identity,
        version="0.3.0",
        snapshot=snapshot,
        capabilities=_beeper_caps(),
    )
    component = payload["components"].get("beeper")
    assert component is not None
    assert component["platform"] == "switch"
    assert component["default_entity_id"] == "switch.dh_pve_agent_ups_beeper"
    assert component["state_topic"] == ups_topics.state
    assert component["command_topic"] == ups_topics.beeper_set
    assert component["payload_on"] == "ON"
    assert component["payload_off"] == "OFF"
    assert "beeper_status" in component["value_template"]

    routed = route_ups_discovery_groups(payload, ups_topics)
    assert routed["components"]["beeper"]["state_topic"].endswith("/ups/state/tests")

    mute_only = parse_upscmd_list_output("beeper.mute - Mute beeper\n")
    unsupported = build_ups_discovery_payload(
        mqtt,
        identity,
        version="0.3.0",
        snapshot=snapshot,
        capabilities=mute_only,
    )
    assert "beeper" not in unsupported["components"]


def test_runtime_executes_beeper_command_and_refreshes_real_feedback(tmp_path):
    assert "beeper_executor" in inspect.signature(UpsRuntime.__init__).parameters

    class Bridge:
        def __init__(self):
            self.ups_reconnect_requested = threading.Event()
            self.ups_refresh_requested = threading.Event()
            self.ups_beeper_updates = queue.SimpleQueue()
            self.discovery = []
            self.states = []
            self.availability = []

        def publish_ups_discovery(self, payload):
            self.discovery.append(payload)
            return True

        def publish_ups_state(self, payload):
            self.states.append(payload)
            return True

        def publish_ups_availability(self, online):
            self.availability.append(online)
            return True

    bridge = Bridge()
    beeper = {"state": "enabled"}
    commands = []

    def reader(config):
        return parse_upsc_output(
            f"ups.status: OL\nups.beeper.status: {beeper['state']}\n"
        )

    def beeper_executor(config, command_name):
        commands.append(command_name)
        beeper["state"] = "enabled" if command_name in {"beeper.on", "beeper.enable"} else "disabled"

    runtime = UpsRuntime(
        config=_ups_config(),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.3.0",
        state_store=StateStore(tmp_path / "ups.json"),
        now_iso=lambda: "2026-09-15T03:00:00+05:00",
        now_monotonic=lambda: 100.0,
        reader=reader,
        capability_reader=lambda config: _beeper_caps(),
        beeper_executor=beeper_executor,
        shutdown_policy_reader=lambda: None,
    )

    assert runtime.startup() is True
    bridge.states.clear()
    bridge.ups_beeper_updates.put(False)

    assert runtime.process_events() is True
    assert commands == ["beeper.off"]
    assert runtime.last_snapshot is not None
    assert runtime.last_snapshot.beeper_status == "disabled"
    assert bridge.states[-1]["beeper_status"] == "disabled"
