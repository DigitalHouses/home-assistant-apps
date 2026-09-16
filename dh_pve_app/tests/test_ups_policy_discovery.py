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


def _components():
    return build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=None
    )["components"]


def test_trigger_v2_discovery_exposes_active_policy_read_only():
    components = _components()
    topics = build_ups_topics(_mqtt(), _identity())

    policy = components["trigger_policy"]
    assert policy["platform"] == "sensor"
    assert policy["default_entity_id"] == "sensor.dh_app_pve_ups_trigger_policy"
    assert policy["state_topic"] == topics.state
    assert "value_json.policy.status" in policy["value_template"]
    template = policy["json_attributes_template"]
    for field in (
        "active_charge_threshold_percent",
        "active_runtime_reserve_seconds",
        "draft_charge_threshold_percent",
        "draft_runtime_reserve_seconds",
        "policy_revision",
        "policy_hash",
        "last_applied",
        "apply_result",
    ):
        assert field in template
    assert policy["entity_category"] == "diagnostic"


def test_trigger_v2_discovery_exposes_draft_numbers_and_explicit_apply_button():
    components = _components()
    topics = build_ups_topics(_mqtt(), _identity())

    charge = components["policy_charge_threshold"]
    assert charge["platform"] == "number"
    assert charge["default_entity_id"] == (
        "number.dh_app_pve_ups_shutdown_battery_charge_threshold"
    )
    assert charge["command_topic"] == topics.policy_charge_threshold_set
    assert charge["state_topic"] == topics.state
    assert "policy.draft.shutdown_battery_charge_threshold_percent" in charge["value_template"]
    assert (charge["min"], charge["max"], charge["step"]) == (10, 30, 5)
    assert charge["entity_category"] == "config"

    reserve = components["policy_runtime_reserve"]
    assert reserve["platform"] == "number"
    assert reserve["default_entity_id"] == "number.dh_app_pve_ups_shutdown_runtime_reserve"
    assert reserve["command_topic"] == topics.policy_runtime_reserve_set
    assert "policy.draft.runtime_reserve_seconds" in reserve["value_template"]
    assert (reserve["min"], reserve["max"], reserve["step"]) == (60, 900, 60)
    assert reserve["unit_of_measurement"] == "s"
    assert reserve["entity_category"] == "config"

    apply = components["policy_apply"]
    assert apply["platform"] == "button"
    assert apply["default_entity_id"] == "button.dh_app_pve_ups_apply_trigger_policy"
    assert apply["command_topic"] == topics.policy_apply
    assert apply["payload_press"] == "PRESS"
    assert apply["entity_category"] == "config"


def test_legacy_onbatt_timer_controls_are_not_exposed():
    components = _components()

    assert "policy_on_battery_delay" not in components
    assert "policy_power_restore_delay" not in components
    for component in components.values():
        command_topic = component.get("command_topic")
        if command_topic is None:
            continue
        assert "/ups/policy/on_battery_delay/" not in command_topic


def test_shutdown_policy_keeps_native_nut_state_read_only():
    component = _components()["shutdown_policy"]
    template = component["json_attributes_template"]

    assert "hostsync_seconds" in template
    assert "finaldelay_seconds" in template
    assert "shutdown_enabled" in template
