"""MQTT debug control must be a non-retained explicit ON/OFF command."""
from app.config import MqttConfig
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity
from app.mqtt_bridge import MqttEvents
from app.runtime_settings import RuntimeSettings
from app.topics import build_topics, build_ups_topics


def _mqtt():
    return MqttConfig(
        host="mqtt", port=1883, username="", password="",
        topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
        discovery_prefix="homeassistant", keepalive_seconds=60,
    )


def _identity():
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a", hostname="pve", node_name="PVE",
    )


def test_discovery_exposes_only_explicit_mqtt_debug_switch():
    mqtt, identity = _mqtt(), _identity()
    p = build_ups_discovery_payload(
        mqtt, identity, version="0.5.69", snapshot=None,
    )
    switch = p["components"]["debug_logging"]
    topics = build_ups_topics(mqtt, identity)
    assert switch["platform"] == "switch"
    assert switch["default_entity_id"] == "switch.dh_pve_agent_ups_debug"
    assert switch["command_topic"] == topics.debug_set
    assert switch["state_topic"] == topics.debug_state
    assert switch["payload_on"] == "ON"
    assert switch["payload_off"] == "OFF"
    assert "value_template" not in switch


def test_debug_control_queue_accepts_exact_on_off_values():
    mqtt, identity = _mqtt(), _identity()
    events = MqttEvents(build_topics(mqtt, identity), RuntimeSettings())
    topics = build_ups_topics(mqtt, identity)
    events.configure_ups(topics)
    assert events.handle_message(topics.debug_set, b"ON") is True
    assert events.ups_debug_updates.get_nowait() is True
    assert events.handle_message(topics.debug_set, b"OFF") is True
    assert events.ups_debug_updates.get_nowait() is False
    assert events.handle_message(topics.debug_set, b"PRESS") is False
    assert events.ups_debug_updates.empty()


def test_explicit_ups_debug_does_not_replace_main_ups_state():
    mqtt, identity = _mqtt(), _identity()
    topics = build_ups_topics(mqtt, identity)
    assert topics.debug_set.endswith("/ups/debug/set")
    assert topics.debug_state.endswith("/ups/debug/state")
    assert topics.state != topics.debug_state
    assert topics.diagnostic_event != topics.debug_state
