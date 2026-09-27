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


class FakeMessage:
    def __init__(self, topic, payload=b"value", *, retain=True):
        self.topic = topic
        self.payload = payload
        self.retain = retain


class FakeClient:
    def __init__(self, *, fail_topic=None, retained_topics=()):
        self.fail_topic = fail_topic
        self.retained_topics = tuple(retained_topics)
        self.on_connect = None
        self.on_message = None
        self.username = None
        self.password = None
        self.connected_to = None
        self.loop_started = False
        self.disconnected = False
        self.published = []
        self.subscriptions = []

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

    def subscribe(self, topic_filter, qos):
        self.subscriptions.append((topic_filter, qos))
        if self.on_message is not None:
            for topic in self.retained_topics:
                self.on_message(self, None, FakeMessage(topic))
        return (0, 1)

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


def test_cleanup_deletes_entire_instance_namespace_and_all_discovery_topics():
    config = _config()
    identity = _identity()
    pve = build_topics(config.mqtt, identity)
    ups = build_ups_topics(config.mqtt, identity)
    retained = (
        pve.availability,
        f"{pve.base}/problems/aggregate",
        f"{pve.base}/state/storage/truenas_data",
        f"{pve.base}/settings/cpu_temperature_threshold/state",
        ups.availability,
        f"{ups.base}/state/status",
        f"{ups.base}/problems/low_battery/state",
    )
    client = FakeClient(retained_topics=retained)

    assert cleanup_mqtt(
        config,
        identity,
        client_factory=lambda: client,
        timeout_seconds=0.1,
        scan_seconds=0,
    ) is True

    published = set(client.published)
    for topic in retained:
        assert (topic, "", 1, True) in published

    for topic in (
        pve.discovery,
        ups.discovery,
        *pve.legacy_discoveries,
        *ups.legacy_discoveries,
    ):
        assert (topic, "", 1, True) in published

    assert (
        "homeassistant/device/digitalhouses_proxmox_node_a/config",
        "",
        1,
        True,
    ) in published
    assert client.subscriptions == [(f"{pve.base}/#", 1)]
    assert all(payload == "" for _topic, payload, _qos, _retain in client.published)
    assert client.username == "cleanup-user"
    assert client.password == "cleanup-pass"
    assert client.connected_to == ("mqtt.example", 1884, 45)
    assert client.disconnected is True


def test_cleanup_is_idempotent_when_instance_namespace_is_already_empty():
    config = _config()
    identity = _identity()
    pve = build_topics(config.mqtt, identity)
    ups = build_ups_topics(config.mqtt, identity)
    client = FakeClient()

    assert cleanup_mqtt(
        config,
        identity,
        client_factory=lambda: client,
        timeout_seconds=0.1,
        scan_seconds=0,
    ) is True

    published = set(client.published)
    assert (pve.discovery, "", 1, True) in published
    assert (ups.discovery, "", 1, True) in published
    assert (pve.availability, "", 1, True) in published
    assert (ups.availability, "", 1, True) in published


def test_cleanup_failure_returns_false_but_attempts_remaining_tombstones():
    config = _config()
    identity = _identity()
    pve = build_topics(config.mqtt, identity)
    ups = build_ups_topics(config.mqtt, identity)
    state_topic = f"{pve.base}/state/cpu"
    client = FakeClient(
        fail_topic=ups.discovery,
        retained_topics=(state_topic,),
    )

    assert cleanup_mqtt(
        config,
        identity,
        client_factory=lambda: client,
        timeout_seconds=0.1,
        scan_seconds=0,
    ) is False

    assert (state_topic, "", 1, True) in client.published
    assert (ups.discovery, "", 1, True) in client.published
    for topic in ups.legacy_discoveries:
        assert (topic, "", 1, True) in client.published
