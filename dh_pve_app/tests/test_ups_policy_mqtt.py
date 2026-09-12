import pytest

from app.config import MqttConfig
from app.identity import HostIdentity
from app.mqtt_bridge import MqttBridge, MqttEvents
from app.runtime_settings import RuntimeSettings
from app.topics import build_topics, build_ups_topics
from app.ups_policy import PolicyValidationError


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


def test_policy_topics_are_under_selected_ups_namespace():
    pve = build_topics(_mqtt(), _identity())
    ups = build_ups_topics(_mqtt(), _identity())

    assert ups.policy_on_battery_delay_set == f"{pve.base}/ups/policy/on_battery_delay/set"
    assert ups.policy_power_restore_delay_set == f"{pve.base}/ups/policy/power_restore_delay/set"
    assert ups.policy_apply == f"{pve.base}/ups/policy/apply"
    assert not hasattr(ups, "policy_emergency_runtime_reserve_set")


@pytest.mark.parametrize(
    ("topic_attr", "payload", "expected_key", "expected_value"),
    (
        ("policy_on_battery_delay_set", b"30", "on_battery_delay_minutes", 30),
        ("policy_power_restore_delay_set", b"120", "power_restore_delay_seconds", 120),
    ),
)
def test_policy_number_commands_are_validated_and_queued(
    topic_attr, payload, expected_key, expected_value
):
    events = MqttEvents(build_topics(_mqtt(), _identity()), RuntimeSettings())
    ups = build_ups_topics(_mqtt(), _identity())
    events.configure_ups(ups)

    assert events.handle_message(getattr(ups, topic_attr), payload) is True
    update = events.ups_policy_updates.get_nowait()

    assert update.key == expected_key
    assert update.value == expected_value


@pytest.mark.parametrize(
    ("topic_attr", "payload"),
    (
        ("policy_on_battery_delay_set", b"31"),
        ("policy_power_restore_delay_set", b"125"),
        ("policy_power_restore_delay_set", b"not-a-number"),
    ),
)
def test_policy_number_commands_reject_invalid_direct_mqtt_values(topic_attr, payload):
    events = MqttEvents(build_topics(_mqtt(), _identity()), RuntimeSettings())
    ups = build_ups_topics(_mqtt(), _identity())
    events.configure_ups(ups)

    with pytest.raises(PolicyValidationError):
        events.handle_message(getattr(ups, topic_attr), payload)


def test_removed_runtime_reserve_topic_is_not_handled():
    events = MqttEvents(build_topics(_mqtt(), _identity()), RuntimeSettings())
    ups = build_ups_topics(_mqtt(), _identity())
    events.configure_ups(ups)
    pve = build_topics(_mqtt(), _identity())

    assert events.handle_message(
        f"{pve.base}/ups/policy/emergency_runtime_reserve/set", b"15"
    ) is False


def test_apply_policy_press_sets_dedicated_event():
    events = MqttEvents(build_topics(_mqtt(), _identity()), RuntimeSettings())
    ups = build_ups_topics(_mqtt(), _identity())
    events.configure_ups(ups)

    assert events.handle_message(ups.policy_apply, b"PRESS") is True
    assert events.ups_policy_apply_requested.is_set()
    assert events.handle_message(ups.policy_apply, b"anything-else") is False


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


def test_policy_command_topics_are_subscribed_statically_on_connect():
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
    assert ups.policy_on_battery_delay_set in subscribed
    assert ups.policy_power_restore_delay_set in subscribed
    assert ups.policy_apply in subscribed
    assert f"{pve.base}/ups/policy/emergency_runtime_reserve/set" not in subscribed
