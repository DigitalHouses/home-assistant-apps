import json

import pytest

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


def _bridge():
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
    pve_topics = build_topics(config, identity)
    ups_topics = build_ups_topics(config, identity)
    client = _Client()
    bridge = MqttBridge(
        config,
        pve_topics,
        RuntimeSettings(),
        {"device": {"name": "DH PVE"}},
        client=client,
    )
    bridge.configure_ups(ups_topics)
    bridge.connected.set()
    return bridge, client, ups_topics


def test_ups_problem_publishers_use_owned_retained_topics_only():
    bridge, client, topics = _bridge()

    assert bridge.publish_ups_problem_state("on_battery", True) is True
    assert bridge.publish_ups_problem_aggregate(1) is True
    assert bridge.publish_ups_problem_presentation(
        {"severity": "warning", "summary": "1 active problem", "active": []}
    ) is True

    state, aggregate, presentation = client.published
    assert state == (
        f"{topics.base}/problems/on_battery/state",
        "ON",
        1,
        True,
    )
    assert aggregate == (f"{topics.base}/problems/aggregate", "1", 1, True)
    assert presentation[0] == f"{topics.base}/problems/presentation"
    assert presentation[2:] == (1, True)
    assert json.loads(presentation[1])["severity"] == "warning"


def test_ups_problem_publishers_reject_arbitrary_problem_topic_segments():
    bridge, _client, _topics = _bridge()

    for problem_id in ("../battery", "ups/battery", "low battery", ""):
        with pytest.raises(ValueError):
            bridge.publish_ups_problem_state(problem_id, True)


def test_legacy_ups_discovery_cleanup_clears_both_old_device_topics():
    bridge, client, topics = _bridge()

    assert bridge.clear_legacy_ups_discovery() is True

    assert client.published == [
        (topics.legacy_discoveries[0], "", 1, True),
        (topics.legacy_discoveries[1], "", 1, True),
    ]
