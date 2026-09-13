from app.config import MqttConfig
from app.identity import HostIdentity
from app.mqtt_bridge import MqttBridge, MqttEvents
from app.runtime_settings import RuntimeSettings
from app.topics import build_topics, build_ups_topics


def _mqtt():
    return MqttConfig(
        host="mqtt",
        port=1883,
        username="",
        password="",
        topic_prefix="DigitalHouses/Global/dh_pve_app",
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


def test_legacy_policy_command_topics_are_not_handled():
    events = MqttEvents(build_topics(_mqtt(), _identity()), RuntimeSettings())
    ups = build_ups_topics(_mqtt(), _identity())
    events.configure_ups(ups)

    assert events.handle_message(ups.policy_on_battery_delay_set, b"30") is False
    assert events.handle_message(ups.policy_power_restore_delay_set, b"120") is False
    assert events.handle_message(ups.policy_apply, b"PRESS") is False
    assert not hasattr(events, "ups_policy_updates")
    assert not hasattr(events, "ups_policy_apply_requested")


class _PublishInfo:
    rc = 0

    def wait_for_publish(self, timeout=None):
        return None

    def is_published(self):
        return True


class _Client:
    def __init__(self):
        self.subscriptions = []
        self.published = []

    def will_set(self, *args, **kwargs):
        return None

    def username_pw_set(self, *args, **kwargs):
        return None

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))
        return (0, len(self.subscriptions))

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        return _PublishInfo()


def test_policy_command_topics_are_not_subscribed_on_connect():
    mqtt = _mqtt()
    identity = _identity()
    pve = build_topics(mqtt, identity)
    ups = build_ups_topics(mqtt, identity)
    client = _Client()
    bridge = MqttBridge(
        mqtt,
        pve,
        RuntimeSettings(),
        discovery_payload={},
        client=client,
    )
    bridge.configure_ups(ups)

    bridge._on_connect(client, None, None, 0, None)

    subscribed = {topic for topic, _qos in client.subscriptions}
    assert ups.policy_on_battery_delay_set not in subscribed
    assert ups.policy_power_restore_delay_set not in subscribed
    assert ups.policy_apply not in subscribed

    assert ups.test_quick_interval_days_set in subscribed
    assert ups.test_quick_time_set in subscribed
    assert ups.test_deep_interval_days_set in subscribed
    assert ups.test_deep_time_set in subscribed
