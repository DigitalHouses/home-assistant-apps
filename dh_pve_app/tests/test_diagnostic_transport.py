import json

from app.config import MqttConfig
from app.identity import HostIdentity
from app.mqtt_bridge import MqttBridge
from app.runtime_settings import RuntimeSettings
from app.topics import build_topics, build_ups_topics


class _Info:
    rc = 0

    def wait_for_publish(self, timeout=None):
        return None

    def is_published(self):
        return True


class _Client:
    def __init__(self):
        self.published = []
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None

    def username_pw_set(self, username, password):
        return None

    def will_set(self, topic, payload, qos, retain):
        return None

    def publish(self, topic, payload, qos, retain):
        self.published.append((topic, payload, qos, retain))
        return _Info()


def _objects():
    config = MqttConfig(
        host="mqtt",
        port=1883,
        username="",
        password="",
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
    ups_topics = build_ups_topics(config, identity)
    client = _Client()
    bridge = MqttBridge(
        config,
        topics,
        RuntimeSettings(),
        {"device": {"name": "DH PVE"}},
        client=client,
    )
    bridge.configure_ups(ups_topics)
    bridge.connected.set()
    return bridge, client, topics, ups_topics


def test_diagnostic_topics_are_separate_from_retained_state_roots():
    _bridge, _client, topics, ups_topics = _objects()

    assert topics.diagnostic_event == f"{topics.base}/event/diagnostic"
    assert ups_topics.diagnostic_event == f"{topics.base}/ups/event/diagnostic"
    assert topics.diagnostic_event != topics.state
    assert ups_topics.diagnostic_event != ups_topics.state


def test_pve_diagnostic_event_is_qos1_json_and_not_retained():
    bridge, client, topics, _ups_topics = _objects()
    payload = {
        "schema_version": 1,
        "event_type": "problem_started",
        "category": "cpu",
        "severity": "warning",
        "object_id": "cpu",
        "object_name": "CPU",
        "metric": "temperature_c",
        "value": 95.0,
        "average": 92.5,
        "threshold": 90.0,
        "summary": "CPU temperature high",
        "details": "Average 92.5 °C; threshold 90 °C",
        "active_problem_count": 1,
    }

    assert bridge.publish_diagnostic_event(payload) is True
    assert bridge.publish_state({"cpu": 95.0}) is True

    event = next(item for item in client.published if item[0] == topics.diagnostic_event)
    state = next(item for item in client.published if item[0] == topics.state)
    assert event[2:] == (1, False)
    assert json.loads(event[1]) == payload
    assert state[2:] == (1, True)


def test_ups_diagnostic_event_is_qos1_json_and_not_retained():
    bridge, client, _topics, ups_topics = _objects()
    payload = {
        "schema_version": 1,
        "event_type": "problem_recovered",
        "category": "ups",
        "severity": "warning",
        "object_id": "ups",
        "object_name": "UPS",
        "metric": "on_battery",
        "value": False,
        "average": None,
        "threshold": None,
        "summary": "UPS online",
        "details": "Utility power restored",
        "active_problem_count": 0,
    }

    assert bridge.publish_ups_diagnostic_event(payload) is True
    assert bridge.publish_ups_state({"status": "OL"}) is True

    event = next(item for item in client.published if item[0] == ups_topics.diagnostic_event)
    state = next(item for item in client.published if item[0] == ups_topics.state)
    assert event[2:] == (1, False)
    assert json.loads(event[1]) == payload
    assert state[2:] == (1, True)
