from app.config import MqttConfig
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity
from app.topics import build_ups_topics


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


def test_policy_discovery_exposes_three_draft_numbers_and_apply_button():
    topics = build_ups_topics(_mqtt(), _identity())
    components = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=None
    )["components"]

    on_battery = components["policy_on_battery_delay"]
    assert on_battery["platform"] == "number"
    assert on_battery["default_entity_id"] == "number.dh_pve_ups_policy_on_battery_delay"
    assert on_battery["command_topic"] == topics.policy_on_battery_delay_set
    assert on_battery["state_topic"] == topics.state
    assert "value_json.policy.draft.on_battery_delay_minutes" in on_battery["value_template"]
    assert on_battery["min"] == 5
    assert on_battery["max"] == 60
    assert on_battery["step"] == 5
    assert on_battery["unit_of_measurement"] == "min"
    assert on_battery["mode"] == "slider"

    reserve = components["policy_emergency_runtime_reserve"]
    assert reserve["platform"] == "number"
    assert reserve["default_entity_id"] == "number.dh_pve_ups_policy_emergency_runtime_reserve"
    assert reserve["command_topic"] == topics.policy_emergency_runtime_reserve_set
    assert reserve["min"] == 10
    assert reserve["max"] == 30
    assert reserve["step"] == 1
    assert reserve["unit_of_measurement"] == "min"

    restore = components["policy_power_restore_delay"]
    assert restore["platform"] == "number"
    assert restore["default_entity_id"] == "number.dh_pve_ups_policy_power_restore_delay"
    assert restore["command_topic"] == topics.policy_power_restore_delay_set
    assert restore["min"] == 60
    assert restore["max"] == 300
    assert restore["step"] == 30
    assert restore["unit_of_measurement"] == "s"

    apply_button = components["policy_apply"]
    assert apply_button["platform"] == "button"
    assert apply_button["default_entity_id"] == "button.dh_pve_ups_apply_policy"
    assert apply_button["command_topic"] == topics.policy_apply
    assert apply_button["payload_press"] == "PRESS"


def test_policy_discovery_exposes_status_result_and_last_applied_sensors():
    components = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=None
    )["components"]

    status = components["policy_status"]
    assert status["default_entity_id"] == "sensor.dh_pve_ups_policy_status"
    assert "value_json.policy.status" in status["value_template"]

    result = components["policy_apply_result"]
    assert result["default_entity_id"] == "sensor.dh_pve_ups_policy_apply_result"
    assert "value_json.policy.apply_result" in result["value_template"]

    applied = components["policy_last_applied"]
    assert applied["default_entity_id"] == "sensor.dh_pve_ups_policy_last_applied"
    assert applied["device_class"] == "timestamp"
    assert "value_json.policy.last_applied" in applied["value_template"]
    assert "policy_revision" in applied["json_attributes_template"]
    assert "policy_hash" in applied["json_attributes_template"]


def test_policy_controls_depend_on_app_availability_not_nut_telemetry():
    components = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=None
    )["components"]

    for key in (
        "policy_on_battery_delay",
        "policy_emergency_runtime_reserve",
        "policy_power_restore_delay",
        "policy_apply",
        "policy_status",
        "policy_apply_result",
        "policy_last_applied",
    ):
        availability = components[key]["availability"]
        assert len(availability) == 1
        assert "value_json.available" not in str(availability)
