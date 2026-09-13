import pytest

from app.config import MqttConfig
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity
from app.ups_policy import (
    PolicyValidationError,
    UpsPolicyDraft,
    parse_policy_value,
    policy_hash,
    validate_policy,
)


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


def test_commissioning_policy_contains_only_wait_and_restore_delay():
    draft = UpsPolicyDraft(
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
    )

    assert draft.as_dict() == {
        "on_battery_delay_minutes": 30,
        "power_restore_delay_seconds": 120,
    }
    assert len(policy_hash(draft)) == 64


def test_emergency_runtime_reserve_is_not_a_commissioning_policy_value():
    with pytest.raises(PolicyValidationError, match="Неизвестный параметр"):
        parse_policy_value("emergency_runtime_reserve_minutes", "15")


def test_commissioning_policy_validation_has_no_runtime_reserve_contract():
    draft = UpsPolicyDraft(
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
    )

    result = validate_policy(draft)

    assert result.on_battery_delay_seconds == 1800
    assert result.power_restore_delay_seconds == 120
    assert not hasattr(result, "emergency_runtime_reserve_seconds")


def test_home_assistant_policy_surface_is_read_only():
    components = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=None
    )["components"]

    assert "policy_apply" not in components
    assert "policy_on_battery_delay" not in components
    assert "policy_power_restore_delay" not in components

    wait = components["policy_on_battery_delay_observed"]
    restore = components["policy_power_restore_delay_observed"]
    assert wait["platform"] == "sensor"
    assert restore["platform"] == "sensor"
    assert "command_topic" not in wait
    assert "command_topic" not in restore
