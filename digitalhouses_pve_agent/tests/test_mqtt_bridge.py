import logging
import threading
from types import SimpleNamespace

from app.config import MqttConfig
from app.identity import HostIdentity
from app.mqtt_bridge import MqttBridge, MqttEvents, build_lwt
from app.runtime_settings import RuntimeSettings
from app.topics import build_topics, build_ups_topics


def _mqtt():
    return MqttConfig(
        host="mqtt",
        port=1883,
        username="",
        password="",
        topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
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


def _topics():
    return build_topics(_mqtt(), _identity())


def test_lwt_is_retained_offline_availability():
    will = build_lwt(_topics())

    assert will.topic.endswith("/availability")
    assert will.payload == "offline"
    assert will.qos == 1
    assert will.retain is True


def test_refresh_press_sets_event():
    topics = _topics()
    events = MqttEvents(topics, RuntimeSettings())

    assert events.handle_message(topics.refresh, b"PRESS") is True
    assert events.refresh_requested.is_set()


def test_duplicate_refresh_presses_are_ignored_while_pending_or_running():
    topics = _topics()
    events = MqttEvents(topics, RuntimeSettings())

    assert events.handle_message(topics.refresh, b"PRESS") is True
    assert events.refresh_requested.is_set()

    assert events.handle_message(topics.refresh, b"PRESS") is True
    assert events.refresh_requested.is_set()

    events.refresh_requested.clear()
    events.refresh_in_progress.set()
    assert events.handle_message(topics.refresh, b"PRESS") is True
    assert not events.refresh_requested.is_set()


def test_fan_calibration_press_sets_dedicated_event():
    topics = _topics()
    events = MqttEvents(topics, RuntimeSettings())

    assert events.handle_message(topics.fan_calibrate, b"PRESS") is True
    assert events.fan_calibration_requested.is_set()
    assert not events.refresh_requested.is_set()


def test_retired_poll_setting_command_is_not_accepted():
    topics = _topics()
    settings = RuntimeSettings()
    events = MqttEvents(topics, settings)
    topic = f"{topics.settings_prefix}/fast_poll_interval_seconds/set"

    assert events.handle_message(topic, b"20") is False
    assert events.setting_updates.empty()


def test_removed_publish_delta_command_is_not_accepted():
    topics = _topics()
    settings = RuntimeSettings()
    events = MqttEvents(topics, settings)
    topic = f"{topics.settings_prefix}/cpu_publish_delta/set"

    assert events.handle_message(topic, b"7") is False
    assert events.setting_updates.empty()


def test_unknown_topic_is_ignored():
    events = MqttEvents(_topics(), RuntimeSettings())

    assert events.handle_message("some/other/topic", b"x") is False


def test_main_refresh_queues_only_global_refresh_event():
    events = MqttEvents(_topics(), RuntimeSettings())
    ups = build_ups_topics(_mqtt(), _identity())
    events.configure_ups(ups)

    assert events.handle_message(events.topics.refresh, b"PRESS") is True
    assert events.refresh_requested.is_set()
    assert not events.ups_refresh_requested.is_set()


def test_duplicate_ups_refresh_press_is_ignored_while_running():
    events = MqttEvents(_topics(), RuntimeSettings())
    ups = build_ups_topics(_mqtt(), _identity())
    events.configure_ups(ups)

    events.ups_refresh_in_progress.set()
    assert events.handle_message(ups.refresh, b"PRESS") is True
    assert not events.ups_refresh_requested.is_set()


def test_ups_refresh_uses_separate_event():
    events = MqttEvents(_topics(), RuntimeSettings())
    ups = build_ups_topics(_mqtt(), _identity())
    events.configure_ups(ups)

    assert events.handle_message(ups.refresh, b"PRESS") is True
    assert events.ups_refresh_requested.is_set()
    assert not events.refresh_requested.is_set()


def test_ha_online_sets_pve_and_ups_reconnect_events():
    events = MqttEvents(_topics(), RuntimeSettings())
    ups = build_ups_topics(_mqtt(), _identity())
    events.configure_ups(ups)

    events.handle_ha_online()

    assert events.reconnect_requested.is_set()
    assert events.ups_reconnect_requested.is_set()


def test_restart_press_sets_single_request_and_rejects_other_payloads():
    topics = _topics()
    events = MqttEvents(topics, RuntimeSettings())

    assert events.handle_message(topics.restart_agent, b"INVALID") is False
    assert not events.restart_requested.is_set()
    assert events.handle_message(topics.restart_agent, b"PRESS") is True
    assert events.handle_message(topics.restart_agent, b"PRESS") is True
    assert events.restart_requested.is_set()


def test_restart_retained_command_is_ignored_but_live_press_is_accepted():
    topics = _topics()
    events = MqttEvents(topics, RuntimeSettings())
    bridge = object.__new__(MqttBridge)
    bridge.topics = topics
    bridge.log = logging.getLogger(__name__)
    bridge.handle_message = events.handle_message
    bridge.wake_requested = threading.Event()
    message = SimpleNamespace(topic=topics.restart_agent, payload=b"PRESS", retain=True)

    bridge._on_message(None, None, message)
    assert not events.restart_requested.is_set()

    message.retain = False
    bridge._on_message(None, None, message)
    assert events.restart_requested.is_set()
    assert bridge.wake_requested.is_set()


def test_mqtt_connection_subscribes_to_restart_command():
    topics = _topics()
    bridge = object.__new__(MqttBridge)
    MqttEvents.__init__(bridge, topics, RuntimeSettings())
    bridge.connected = threading.Event()
    bridge.wake_requested = threading.Event()
    bridge.log = logging.getLogger(__name__)

    class Client:
        def __init__(self):
            self.subscriptions = []

        def subscribe(self, topic, qos=0):
            self.subscriptions.append((topic, qos))

        def publish(self, *args, **kwargs):
            return None

    client = Client()
    bridge._on_connect(client, None, None, SimpleNamespace(is_failure=False), None)

    assert (topics.restart_agent, 1) in client.subscriptions
