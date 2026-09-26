import json

import pytest

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


def _bridge():
    config = MqttConfig(
        host="mqtt",
        port=1883,
        username="",
        password="",
        topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
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
    bridge = MqttBridge(
        config,
        topics,
        RuntimeSettings(),
        {"device": {"name": "DH PVE"}},
        client=client,
    )
    bridge.connected.set()
    return bridge, client, topics


def test_problem_publishers_use_owned_retained_topics_only():
    bridge, client, topics = _bridge()

    assert bridge.publish_problem_metric(
        "cpu_temperature",
        {"metric": "temperature_c", "value": 95.0, "average": 92.5},
    ) is True
    assert bridge.publish_problem_state("cpu_temperature", True) is True
    assert bridge.publish_problem_aggregate(1) is True
    assert bridge.publish_problem_presentation(
        {"severity": "warning", "summary": "1 active problem", "active": []}
    ) is True

    metric, state, aggregate, presentation = client.published
    assert metric[0] == f"{topics.base}/problems/cpu_temperature/metric"
    assert metric[2:] == (1, True)
    assert json.loads(metric[1])["average"] == 92.5
    assert state == (
        f"{topics.base}/problems/cpu_temperature/state",
        "ON",
        1,
        True,
    )
    assert aggregate == (f"{topics.base}/problems/aggregate", "1", 1, True)
    assert presentation[0] == f"{topics.base}/problems/presentation"
    assert presentation[2:] == (1, True)
    assert json.loads(presentation[1])["severity"] == "warning"


def test_problem_publishers_reject_arbitrary_problem_topic_segments():
    bridge, _client, _topics = _bridge()

    for problem_id in ("../cpu", "cpu/temp", "cpu temperature", ""):
        with pytest.raises(ValueError):
            bridge.publish_problem_state(problem_id, True)
