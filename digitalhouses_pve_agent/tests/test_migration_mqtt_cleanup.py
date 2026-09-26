from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from app.config import AppConfig, GeneralConfig, MqttConfig
from app.identity import HostIdentity

ROOT = Path(__file__).parents[1]


class FakeReasonCode:
    is_failure = False


class FakePublishInfo:
    def __init__(self, rc=0, published=True):
        self.rc = rc
        self._published = published

    def wait_for_publish(self, timeout=None):
        return None

    def is_published(self):
        return self._published


class FakeMessage:
    def __init__(self, topic: str, *, retain: bool):
        self.topic = topic
        self.retain = retain
        self.payload = b"retained"


class FakeClient:
    def __init__(self, messages):
        self.messages = list(messages)
        self.on_connect = None
        self.on_message = None
        self.username = None
        self.password = None
        self.connected_to = None
        self.subscriptions = []
        self.published = []
        self.disconnected = False

    def username_pw_set(self, username, password):
        self.username = username
        self.password = password

    def connect(self, host, port, keepalive):
        self.connected_to = (host, port, keepalive)
        return 0

    def loop_start(self):
        if self.on_connect is not None:
            self.on_connect(self, None, None, FakeReasonCode(), None)

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))
        if self.on_message is not None:
            for message in self.messages:
                self.on_message(self, None, message)
        return (0, 1)

    def publish(self, topic, payload, qos, retain):
        self.published.append((topic, payload, qos, retain))
        return FakePublishInfo()

    def disconnect(self):
        self.disconnected = True

    def loop_stop(self):
        return None


def _legacy_config() -> AppConfig:
    return AppConfig(
        general=GeneralConfig(instance_id="", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(
            host="mqtt.example",
            port=1884,
            username="cleanup-user",
            password="cleanup-pass",
            topic_prefix="DigitalHouses/Global/dh_pve_app",
            discovery_prefix="homeassistant",
            keepalive_seconds=45,
        ),
    )


def _identity() -> HostIdentity:
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )


def test_migration_cleanup_removes_only_retained_topics_owned_by_legacy_instance():
    try:
        module = importlib.import_module("app.migration_cleanup")
    except ModuleNotFoundError:
        pytest.fail("app.migration_cleanup is missing")

    cleanup = getattr(module, "cleanup_legacy_mqtt_namespace", None)
    assert callable(cleanup), "cleanup_legacy_mqtt_namespace is missing"

    config = _legacy_config()
    identity = _identity()
    base = "DigitalHouses/Global/dh_pve_app/node_a"

    client = FakeClient(
        [
            FakeMessage(f"{base}/availability", retain=True),
            FakeMessage(f"{base}/state/cpu", retain=True),
            FakeMessage(f"{base}/settings/cpu_temperature/state", retain=True),
            FakeMessage(f"{base}/ups/state/telemetry", retain=True),
            FakeMessage(f"{base}/event/diagnostic", retain=False),
            FakeMessage(
                "DigitalHouses/Global/dh_pve_app/node_ab/state/cpu",
                retain=True,
            ),
            FakeMessage(
                "DigitalHouses/Global/digitalhouses_pve_agent/node_a/state/cpu",
                retain=True,
            ),
        ]
    )

    assert cleanup(
        config,
        identity,
        client_factory=lambda: client,
        connect_timeout_seconds=0.1,
        scan_seconds=0.0,
    ) is True

    assert client.subscriptions == [(f"{base}/#", 1)]

    expected_machine_topics = {
        f"{base}/availability",
        f"{base}/state/cpu",
        f"{base}/settings/cpu_temperature/state",
        f"{base}/ups/state/telemetry",
    }
    expected_discovery_topics = {
        "homeassistant/device/dh_app_pve_node_a/config",
        "homeassistant/device/dh_pve_node_a/config",
        "homeassistant/device/dh_app_pve_ups_node_a/config",
        "homeassistant/device/dh_pve_ups_node_a/config",
        "homeassistant/device/dh_ups_node_a/config",
    }

    tombstones = {
        topic
        for topic, payload, qos, retain in client.published
        if payload == "" and qos == 1 and retain is True
    }

    assert tombstones == expected_machine_topics | expected_discovery_topics
    assert "DigitalHouses/Global/dh_pve_app/node_ab/state/cpu" not in tombstones
    assert (
        "DigitalHouses/Global/digitalhouses_pve_agent/node_a/state/cpu"
        not in tombstones
    )
    assert f"{base}/event/diagnostic" not in tombstones
    assert all("dh_pve_agent_" not in topic for topic in expected_discovery_topics)
    assert client.username == "cleanup-user"
    assert client.password == "cleanup-pass"
    assert client.connected_to == ("mqtt.example", 1884, 45)
    assert client.disconnected is True


def test_installer_runs_legacy_namespace_cleanup_before_canonical_service_start():
    text = (ROOT / "install.sh").read_text(encoding="utf-8")

    cleanup_token = "--migration-mqtt-cleanup"
    restart_token = 'systemctl restart "${SERVICE_NAME}"'

    assert cleanup_token in text
    assert text.index(cleanup_token) < text.index(restart_token)
