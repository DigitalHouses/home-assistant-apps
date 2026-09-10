import json

from app.config import MqttConfig
from app.identity import HostIdentity
from app.mqtt_bridge import MqttBridge
from app.runtime_settings import RuntimeSettings
from app.topics import build_topics


class _Info:
    rc = 0

    def wait_for_publish(self, timeout=None):
        return None

    def is_published(self):
        return True


class _Client:
    def __init__(self):
        self.published = []
        self.subscriptions = []
        self.will = None
        self.username = None
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None

    def username_pw_set(self, username, password):
        self.username = (username, password)

    def will_set(self, topic, payload, qos, retain):
        self.will = (topic, payload, qos, retain)

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))

    def publish(self, topic, payload, qos, retain):
        self.published.append((topic, payload, qos, retain))
        return _Info()

    def connect_async(self, host, port, keepalive):
        self.connection = (host, port, keepalive)

    def loop_start(self):
        self.loop_started = True

    def disconnect(self):
        self.disconnected = True

    def loop_stop(self):
        self.loop_stopped = True


class _Reason:
    is_failure = False


class _Message:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload


def _bridge():
    config = MqttConfig(
        host="mqtt",
        port=1883,
        username="user",
        password="secret",
        topic_prefix="DigitalHouses/Global/dh_pve_app",
        discovery_prefix="homeassistant",
        keepalive_seconds=60,
    )
    identity = HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )
    topics = build_topics(config, identity)
    client = _Client()
    settings = RuntimeSettings()
    bridge = MqttBridge(
        config,
        topics,
        settings,
        {"device": {"name": "DH PVE"}},
        client=client,
    )
    return bridge, client, topics, settings


def test_transport_uses_retained_qos1_lwt_and_subscriptions():
    bridge, client, topics, _ = _bridge()
    assert client.will == (topics.availability, "offline", 1, True)
    bridge._on_connect(client, None, None, _Reason(), None)
    assert (topics.ha_status, 1) in client.subscriptions
    assert (topics.refresh, 1) in client.subscriptions
    assert (f"{topics.settings_prefix}/+/set", 1) in client.subscriptions
    assert (topics.availability, "online", 1, True) in client.published
    assert bridge.reconnect_requested.is_set()


def test_state_and_discovery_are_retained_qos1_json():
    bridge, client, topics, _ = _bridge()
    bridge.connected.set()
    assert bridge.publish_discovery() is True
    assert bridge.publish_state({"cpu": 12.5}) is True
    discovery = next(item for item in client.published if item[0] == topics.discovery)
    state = next(item for item in client.published if item[0] == topics.state)
    assert discovery[2:] == (1, True)
    assert state[2:] == (1, True)
    assert json.loads(state[1]) == {"cpu": 12.5}


def test_invalid_runtime_setting_republishes_effective_value():
    bridge, client, topics, settings = _bridge()
    bridge.connected.set()
    topic = f"{topics.settings_prefix}/cpu_publish_delta/set"
    bridge._on_message(client, None, _Message(topic, b"999"))
    assert settings.get("cpu_publish_delta") == 5.0
    assert (
        f"{topics.settings_prefix}/cpu_publish_delta/state",
        "5",
        1,
        True,
    ) in client.published


def test_ha_online_requests_full_republish():
    bridge, client, topics, _ = _bridge()
    bridge._on_message(client, None, _Message(topics.ha_status, b"online"))
    assert bridge.reconnect_requested.is_set()
    assert bridge.wake_requested.is_set()
