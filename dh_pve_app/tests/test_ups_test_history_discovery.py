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
        _mqtt(),
        _identity(),
        version="0.2.0",
        snapshot=None,
    )["components"]


def test_discovery_exposes_current_test_state_and_history():
    components = _components()

    state = components["test_state"]
    assert state["default_entity_id"] == "sensor.dh_pve_ups_test_state"
    assert "test_schedule.current_state" in state["value_template"]

    history = components["test_history"]
    assert history["default_entity_id"] == "sensor.dh_pve_ups_test_history"
    assert "value_json.test_history" in history["value_template"]
    assert "history" in history["json_attributes_template"]


def test_discovery_exposes_last_and_next_quick_deep_tests():
    components = _components()

    expected = {
        "last_quick_test": "sensor.dh_pve_ups_last_quick_test",
        "next_quick_test": "sensor.dh_pve_ups_next_quick_test",
        "last_deep_test": "sensor.dh_pve_ups_last_deep_test",
        "next_deep_test": "sensor.dh_pve_ups_next_deep_test",
    }
    for key, entity_id in expected.items():
        assert components[key]["default_entity_id"] == entity_id

    assert "quick.last_result" in components["last_quick_test"]["value_template"]
    assert "quick.last_time" in components["last_quick_test"]["json_attributes_template"]
    assert "quick.next_due" in components["next_quick_test"]["value_template"]
    assert components["next_quick_test"]["device_class"] == "timestamp"

    assert "deep.last_result" in components["last_deep_test"]["value_template"]
    assert "deep.last_time" in components["last_deep_test"]["json_attributes_template"]
    assert "deep.next_due" in components["next_deep_test"]["value_template"]
    assert components["next_deep_test"]["device_class"] == "timestamp"
