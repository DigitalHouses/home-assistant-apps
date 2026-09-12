import pytest

from app.config import MqttConfig
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity
from app.mqtt_bridge import MqttEvents
from app.runtime_settings import RuntimeSettings
from app.topics import build_topics, build_ups_topics
from app.ups_test_schedule import TestScheduleError, parse_time_command_payload


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


def test_time_command_payload_normalizes_mqtt_time_to_minute():
    assert parse_time_command_payload("12:00") == "12:00"
    assert parse_time_command_payload("13:45:00") == "13:45"
    assert parse_time_command_payload("13:45:59") == "13:45"

    for value in ("2:00", "24:00:00", "13:60:00", "night"):
        with pytest.raises(TestScheduleError):
            parse_time_command_payload(value)


def test_schedule_topics_are_under_ups_test_namespace():
    topics = build_ups_topics(_mqtt(), _identity())

    assert topics.test_quick_interval_days_set.endswith(
        "/ups/test/schedule/quick/interval_days/set"
    )
    assert topics.test_quick_time_set.endswith("/ups/test/schedule/quick/time/set")
    assert topics.test_deep_interval_days_set.endswith(
        "/ups/test/schedule/deep/interval_days/set"
    )
    assert topics.test_deep_time_set.endswith("/ups/test/schedule/deep/time/set")


def test_schedule_mqtt_updates_are_validated_and_queued():
    pve = build_topics(_mqtt(), _identity())
    ups = build_ups_topics(_mqtt(), _identity())
    events = MqttEvents(pve, RuntimeSettings())
    events.configure_ups(ups)

    assert events.handle_message(ups.test_quick_interval_days_set, b"30") is True
    update = events.ups_test_schedule_updates.get_nowait()
    assert (update.test_type, update.field, update.value) == (
        "quick",
        "interval_days",
        30,
    )

    assert events.handle_message(ups.test_deep_time_set, b"13:15:37") is True
    update = events.ups_test_schedule_updates.get_nowait()
    assert (update.test_type, update.field, update.value) == (
        "deep",
        "preferred_time",
        "13:15",
    )


def test_schedule_mqtt_rejects_invalid_values():
    pve = build_topics(_mqtt(), _identity())
    ups = build_ups_topics(_mqtt(), _identity())
    events = MqttEvents(pve, RuntimeSettings())
    events.configure_ups(ups)

    with pytest.raises(TestScheduleError):
        events.handle_message(ups.test_quick_interval_days_set, b"-1")
    with pytest.raises(TestScheduleError):
        events.handle_message(ups.test_quick_interval_days_set, b"1.5")
    with pytest.raises(TestScheduleError):
        events.handle_message(ups.test_quick_time_set, b"25:00:00")


def test_discovery_exposes_interval_numbers_and_native_mqtt_time_entities():
    topics = build_ups_topics(_mqtt(), _identity())
    components = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=None
    )["components"]

    quick_days = components["test_quick_interval_days"]
    assert quick_days["platform"] == "number"
    assert quick_days["default_entity_id"] == "number.dh_pve_ups_quick_test_interval_days"
    assert quick_days["command_topic"] == topics.test_quick_interval_days_set
    assert quick_days["min"] == 0
    assert quick_days["max"] == 3650
    assert quick_days["step"] == 1
    assert quick_days["mode"] == "box"

    quick_time = components["test_quick_time"]
    assert quick_time["platform"] == "time"
    assert quick_time["default_entity_id"] == "time.dh_pve_ups_quick_test_time"
    assert quick_time["command_topic"] == topics.test_quick_time_set
    assert "test_schedule.quick.preferred_time" in quick_time["value_template"]

    deep_days = components["test_deep_interval_days"]
    assert deep_days["platform"] == "number"
    assert deep_days["default_entity_id"] == "number.dh_pve_ups_deep_test_interval_days"
    assert deep_days["command_topic"] == topics.test_deep_interval_days_set

    deep_time = components["test_deep_time"]
    assert deep_time["platform"] == "time"
    assert deep_time["default_entity_id"] == "time.dh_pve_ups_deep_test_time"
    assert deep_time["command_topic"] == topics.test_deep_time_set


def test_schedule_controls_depend_only_on_app_availability():
    components = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=None
    )["components"]

    for key in (
        "test_quick_interval_days",
        "test_quick_time",
        "test_deep_interval_days",
        "test_deep_time",
    ):
        availability = components[key]["availability"]
        assert len(availability) == 1
        assert "value_json.available" not in str(availability)
