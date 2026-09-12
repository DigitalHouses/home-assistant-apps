from app.config import MqttConfig
from app.identity import HostIdentity
from app.mqtt_bridge import MqttEvents, build_lwt
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


def test_setting_command_is_validated_and_queued():
    topics = _topics()
    settings = RuntimeSettings()
    events = MqttEvents(topics, settings)
    topic = f"{topics.settings_prefix}/cpu_publish_delta/set"

    assert events.handle_message(topic, b"7") is True
    update = events.setting_updates.get_nowait()

    assert update.key == "cpu_publish_delta"
    assert update.value == 7.0
    assert settings.get("cpu_publish_delta") == 7.0


def test_unknown_topic_is_ignored():
    events = MqttEvents(_topics(), RuntimeSettings())

    assert events.handle_message("some/other/topic", b"x") is False


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
