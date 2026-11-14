"""DH Sync v1 MQTT source metadata; no changes to existing PVE topics."""
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from app import main
from app.config import AppConfig, GeneralConfig, MqttConfig, DEFAULT_TOPIC_PREFIX
from app.identity import HostIdentity, resolve_identity
from app.mqtt_bridge import MqttBridge, build_lwt
from app.runtime_settings import RuntimeSettings
from app.sync_discovery import PRODUCT_ID, PRODUCT_PATH, REPOSITORY, build_sync_payload
from app.topics import build_topics, build_ups_topics


ROOT = Path(__file__).resolve().parents[2]


class MockClient:
    def __init__(self):
        self.published = []
        self.subscriptions = []
        self.will = None
        self.start_calls = 0

    def will_set(self, topic, payload, qos, retain):
        self.will = (topic, payload, qos, retain)

    def username_pw_set(self, username, password):
        self.credentials = (username, password)

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))

    def publish(self, topic, payload, qos, retain):
        self.published.append((topic, payload, qos, retain))
        return SimpleNamespace(rc=0)

    def connect_async(self, *args):
        self.start_calls += 1

    def loop_start(self):
        pass


def _config(topic_prefix=DEFAULT_TOPIC_PREFIX):
    return MqttConfig(
        host="localhost", port=1883, username="test_user", password="test_password",
        topic_prefix=topic_prefix, discovery_prefix="homeassistant",
        keepalive_seconds=60,
    )


def _identity(instance_id="node_a"):
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id=instance_id, hostname="pve", node_name="PVE",
    )


def _bridge(instance_id="node_a", version="0.5.88", topic_prefix=DEFAULT_TOPIC_PREFIX):
    config = _config(topic_prefix)
    identity = _identity(instance_id)
    topics = build_topics(config, identity)
    client = MockClient()
    bridge = MqttBridge(
        config, topics, RuntimeSettings(), {"device": {"name": "DH PVE"}},
        client=client, sync_version=version,
    )
    return bridge, client, topics, config, identity


@pytest.mark.parametrize("instance_id", ["node_a", "0123456789abcdef0123456789abcdef"])
def test_existing_instance_identity_defines_canonical_sync_topic(instance_id):
    bridge, client, topics, config, identity = _bridge(instance_id)
    assert topics.sync == f"DigitalHouses/Global/digitalhouses_pve_agent/{instance_id}/sync"
    assert topics.availability == f"{topics.base}/availability"
    assert topics.discovery == f"homeassistant/device/dh_pve_agent_{instance_id}/config"
    assert build_ups_topics(config, identity).availability == f"{topics.base}/ups/availability"
    assert client.will == (topics.availability, "offline", 1, True)


def test_auto_machine_id_instance_uses_stable_existing_identity(tmp_path):
    machine_id = tmp_path / "machine-id"
    machine_id.write_text("a" * 32)
    identity = resolve_identity(
        GeneralConfig(instance_id="", node_name="PVE", log_level="info"),
        machine_id_path=machine_id, hostname="pve",
    )
    assert build_topics(_config(), identity).sync == (
        "DigitalHouses/Global/digitalhouses_pve_agent/" + "a" * 32 + "/sync"
    )


def test_sync_topic_remains_canonical_with_legacy_topic_override():
    _bridge_obj, _, topics, _, _ = _bridge(
        "node_a", topic_prefix="DigitalHouses/Legacy/pve_agent"
    )
    assert topics.base == "DigitalHouses/Legacy/pve_agent/node_a"
    assert topics.availability == "DigitalHouses/Legacy/pve_agent/node_a/availability"
    assert topics.sync == "DigitalHouses/Global/digitalhouses_pve_agent/node_a/sync"


def test_payload_schema_identity_from_registry_and_running_version():
    registry = json.loads(
        (ROOT / "digitalhouses-stats/digitalhouses_stats/product_registry.json")
        .read_text(encoding="utf-8")
    )
    product = next(p for p in registry["products"] if p["id"] == PRODUCT_ID)
    version = main._version()
    payload = json.loads(build_sync_payload(version))
    assert payload == {
        "schema": 1,
        "product_id": "digitalhouses_pve_agent",
        "type": "agent",
        "version": version,
        "repository": "https://github.com/DigitalHouses/home-assistant-apps",
        "product_path": "digitalhouses_pve_agent",
    }
    assert type(payload["schema"]) is int
    assert payload["schema"] == 1
    assert product["type"] == payload["type"]
    assert product["repository_directory"] == payload["product_path"]
    assert payload["product_path"] == payload["product_id"]


def test_repository_fixed_exact_github_owner_and_safe_product_path():
    url = urlsplit(REPOSITORY)
    assert url.scheme == "https"
    assert url.hostname == "github.com"
    assert url.username is None and url.password is None and url.port is None
    assert not url.query and not url.fragment
    assert url.path.split("/") == ["", "DigitalHouses", "home-assistant-apps"]
    assert url.path.split("/")[1].casefold() == "digitalhouses"
    assert "%" not in REPOSITORY and ".." not in REPOSITORY
    assert PRODUCT_PATH == PRODUCT_ID
    assert "/" not in PRODUCT_PATH and PRODUCT_PATH != "."
    # Producer has no input URL; validation of MQTT claims belongs to DH Sync.


def test_connect_and_reconnect_publish_one_retained_qos1_sync_message_each():
    bridge, client, topics, _config_obj, _identity_obj = _bridge(version="9.8.7")
    assert client.published == []
    bridge._on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
    first = [message for message in client.published if message[0] == topics.sync]
    assert len(first) == 1
    assert first[0][2:] == (1, True)
    payload = json.loads(first[0][1])
    assert payload["version"] == "9.8.7"  # not copied from VERSION or example
    assert payload["product_id"] == topics.sync.split("/")[2]
    assert set(payload) == {
        "schema", "product_id", "type", "version", "repository", "product_path"
    }
    assert all(secret not in first[0][1] for secret in (
        "test_password", "test_user", "node_a", "localhost", "192.168",
        "token", "commit", "serial",
    ))
    assert (topics.availability, "online", 1, True) in client.published
    assert client.will == (topics.availability, "offline", 1, True)
    assert (topics.discovery, 1) not in client.subscriptions  # unchanged
    assert topics.sync not in [topic for topic, _ in client.subscriptions]

    bridge._on_disconnect(client, None, None, None, None)
    assert not bridge.connected.is_set()
    assert len([p for p in client.published if p[0] == topics.sync]) == 1
    bridge._on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
    assert len([p for p in client.published if p[0] == topics.sync]) == 2


def test_connect_rejected_does_not_publish_or_schedule_extra_retries():
    bridge, client, topics, _, _ = _bridge()
    bridge._on_connect(client, None, None, SimpleNamespace(is_failure=True), None)
    assert not bridge.connected.is_set()
    assert client.published == []
    assert client.start_calls == 0


def test_existing_runtime_wires_actual_version_not_a_literal(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "resolve_identity", lambda *_: _identity())
    monkeypatch.setattr(main, "_version", lambda: "3.2.1")
    app_config = AppConfig(
        general=GeneralConfig(instance_id="node_a", node_name="PVE", log_level="info"),
        mqtt=_config(),
    )
    bridge, runtime = main.build_runtime(app_config, state_dir=tmp_path)
    assert json.loads(bridge.sync_payload)["version"] == "3.2.1"
    assert runtime.app_version == "3.2.1"


def test_unchanged_legacy_bridge_constructed_without_sync_version():
    bridge, client, topics, _, _ = _bridge()
    old_bridge = MqttBridge(
        _config(), topics, RuntimeSettings(), {"device": {"name": "DH PVE"}},
        client=client,
    )
    client.published.clear()
    old_bridge._on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
    assert not [p for p in client.published if p[0] == topics.sync]
    assert (topics.availability, "online", 1, True) in client.published
    assert build_lwt(topics).topic == topics.availability


def test_no_periodic_sync_publish_on_state_updates_or_ha_birth():
    bridge, client, topics, _, _ = _bridge()
    bridge._on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
    original_count = sum(1 for t, *_ in client.published if t == topics.sync)
    bridge.handle_ha_online()
    bridge.publish_state({"cpu": 3.4})
    assert sum(1 for t, *_ in client.published if t == topics.sync) == original_count
