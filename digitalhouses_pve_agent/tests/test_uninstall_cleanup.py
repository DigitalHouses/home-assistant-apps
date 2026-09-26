from app.config import AppConfig, GeneralConfig, MqttConfig
from app.identity import HostIdentity
from app.topics import build_topics, build_ups_topics
from app.uninstall_cleanup import cleanup_mqtt


class FakeReasonCode:
    is_failure = False


class FakePublishInfo:
    def __init__(self, rc=0, published=True):
        self.rc = rc
        self._published = published
        self.waited = False

    def wait_for_publish(self, timeout=None):
        self.waited = True

    def is_published(self):
        return self._published


class FakeClient:
    def __init__(self, *, fail_topic=None):
        self.fail_topic = fail_topic
        self.on_connect = None
        self.username = None
        self.password = None
        self.connected_to = None
        self.loop_started = False
        self.disconnected = False
        self.published = []

    def username_pw_set(self, username, password):
        self.username = username
        self.password = password

    def connect(self, host, port, keepalive):
        self.connected_to = (host, port, keepalive)
        return 0

    def loop_start(self):
        self.loop_started = True
        if self.on_connect is not None:
            self.on_connect(self, None, None, FakeReasonCode(), None)

    def publish(self, topic, payload, qos, retain):
        self.published.append((topic, payload, qos, retain))
        return FakePublishInfo(rc=1 if topic == self.fail_topic else 0)

    def disconnect(self):
        self.disconnected = True

    def loop_stop(self):
        self.loop_started = False


def _config():
    return AppConfig(
        general=GeneralConfig(instance_id="", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(
            host="mqtt.example",
            port=1884,
            username="cleanup-user",
            password="cleanup-pass",
            topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
            discovery_prefix="homeassistant",
            keepalive_seconds=45,
        ),
    )


def _identity():
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )


def test_cleanup_publishes_offline_then_canonical_and_legacy_discovery_tombstones():
    config = _config()
    identity = _identity()
    client = FakeClient()
    pve = build_topics(config.mqtt, identity)
    ups = build_ups_topics(config.mqtt, identity)

    assert cleanup_mqtt(
        config,
        identity,
        client_factory=lambda: client,
        timeout_seconds=0.1,
    ) is True

    expected = [
        (pve.availability, "offline", 1, True),
        (ups.availability, "offline", 1, True),
        (pve.discovery, "", 1, True),
        (ups.discovery, "", 1, True),
        *[(topic, "", 1, True) for topic in pve.legacy_discoveries],
        *[(topic, "", 1, True) for topic in ups.legacy_discoveries],
    ]
    assert client.published == expected
    assert client.username == "cleanup-user"
    assert client.password == "cleanup-pass"
    assert client.connected_to == ("mqtt.example", 1884, 45)
    assert client.disconnected is True


def test_cleanup_failure_returns_false_but_attempts_remaining_tombstones():
    config = _config()
    identity = _identity()
    ups = build_ups_topics(config.mqtt, identity)
    client = FakeClient(fail_topic=ups.discovery)

    assert cleanup_mqtt(
        config,
        identity,
        client_factory=lambda: client,
        timeout_seconds=0.1,
    ) is False

    assert (ups.discovery, "", 1, True) in client.published
    for topic in ups.legacy_discoveries:
        assert (topic, "", 1, True) in client.published
