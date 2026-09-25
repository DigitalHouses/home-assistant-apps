from app.config import MqttConfig
from app.identity import HostIdentity
from app.mqtt_bridge import MqttBridge
from app.runtime_settings import RuntimeSettings
from app.topics import build_topics


class _PublishInfo:
    rc = 0

    def wait_for_publish(self, timeout=None):
        return None

    def is_published(self):
        return True


class _Client:
    def __init__(self):
        self.published = []

    def username_pw_set(self, username, password):
        pass

    def will_set(self, topic, payload=None, qos=0, retain=False):
        pass

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        return _PublishInfo()


def _mqtt():
    return MqttConfig(
        host="127.0.0.1",
        port=1883,
        username="",
        password="",
        discovery_prefix="homeassistant",
        topic_prefix="DigitalHouses/Global/dh_pve_app",
        keepalive_seconds=60,
    )


def _identity():
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )


def test_pve_topics_expose_previous_device_discovery_for_tombstone():
    topics = build_topics(_mqtt(), _identity())

    assert topics.device_id == "dh_app_pve_node_a"
    assert topics.discovery == "homeassistant/device/dh_app_pve_node_a/config"
    assert topics.legacy_discoveries == (
        "homeassistant/device/dh_pve_node_a/config",
    )


def test_pve_legacy_discovery_cleanup_publishes_retained_empty_payload():
    topics = build_topics(_mqtt(), _identity())
    client = _Client()
    bridge = MqttBridge(
        _mqtt(),
        topics,
        RuntimeSettings(),
        {},
        client=client,
    )
    bridge.connected.set()

    assert bridge.clear_legacy_pve_discovery() is True
    assert client.published == [
        ("homeassistant/device/dh_pve_node_a/config", "", 1, True),
    ]
