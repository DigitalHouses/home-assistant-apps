import pytest

from app.config import MqttConfig
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity
from app.topics import build_ups_topics
from app.ups_policy import PolicyValidationError, UpsPolicyDraft, parse_policy_value, policy_hash, validate_policy


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


def test_policy_draft_contains_only_wait_and_restore_delay():
    draft = UpsPolicyDraft(
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
    )

    assert draft.as_dict() == {
        "on_battery_delay_minutes": 30,
        "power_restore_delay_seconds": 120,
    }
    assert len(policy_hash(draft)) == 64


def test_emergency_runtime_reserve_is_not_a_writable_policy_value():
    with pytest.raises(PolicyValidationError, match="Неизвестный параметр"):
        parse_policy_value("emergency_runtime_reserve_minutes", "15")


def test_policy_validation_has_no_runtime_reserve_contract():
    draft = UpsPolicyDraft(
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
    )

    result = validate_policy(draft)

    assert result.on_battery_delay_seconds == 1800
    assert result.power_restore_delay_seconds == 120
    assert not hasattr(result, "emergency_runtime_reserve_seconds")
    assert not hasattr(result, "minimum_emergency_runtime_reserve_seconds")
    assert not hasattr(result, "recommended_emergency_runtime_reserve_seconds")


def test_mqtt_and_discovery_do_not_expose_emergency_runtime_reserve():
    topics = build_ups_topics(_mqtt(), _identity())
    components = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=None
    )["components"]

    assert not hasattr(topics, "policy_emergency_runtime_reserve_set")
    assert "policy_emergency_runtime_reserve" not in components
    assert components["policy_on_battery_delay"]["command_topic"] == topics.policy_on_battery_delay_set
    assert components["policy_power_restore_delay"]["command_topic"] == topics.policy_power_restore_delay_set
