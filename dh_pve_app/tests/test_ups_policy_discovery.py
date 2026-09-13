from app.config import MqttConfig
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity


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


def _components():
    return build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=None
    )["components"]


def test_policy_discovery_exposes_effective_delays_as_read_only_sensors():
    components = _components()

    on_battery = components["policy_on_battery_delay_observed"]
    assert on_battery["platform"] == "sensor"
    assert on_battery["default_entity_id"] == "sensor.dh_pve_ups_policy_on_battery_delay"
    assert "command_topic" not in on_battery
    assert "value_json.shutdown_policy.on_battery_delay_minutes" in on_battery["value_template"]
    assert on_battery["unit_of_measurement"] == "min"

    restore = components["policy_power_restore_delay_observed"]
    assert restore["platform"] == "sensor"
    assert restore["default_entity_id"] == "sensor.dh_pve_ups_policy_power_restore_delay"
    assert "command_topic" not in restore
    assert "value_json.shutdown_policy.power_restore_delay_seconds" in restore["value_template"]
    assert restore["unit_of_measurement"] == "s"


def test_policy_discovery_has_no_runtime_apply_or_draft_controls():
    components = _components()

    for key in (
        "policy_on_battery_delay",
        "policy_power_restore_delay",
        "policy_apply",
        "policy_status",
        "policy_apply_result",
        "policy_last_applied",
    ):
        assert key not in components

    for component in components.values():
        command_topic = component.get("command_topic")
        if command_topic is None:
            continue
        assert "/ups/policy/" not in command_topic


def test_shutdown_policy_attributes_include_effective_delays():
    component = _components()["shutdown_policy"]
    template = component["json_attributes_template"]

    assert "on_battery_delay_minutes" in template
    assert "power_restore_delay_seconds" in template
    assert "guest_shutdown_budget_seconds" in template
