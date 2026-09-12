import inspect

from app.config import MqttConfig
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity
from app.ups_control import parse_upscmd_list_output


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


def test_battery_test_buttons_require_both_capability_and_command_credentials():
    assert "controls_enabled" in inspect.signature(build_ups_discovery_payload).parameters
    caps = parse_upscmd_list_output(
        "test.battery.start.quick - Start quick test\n"
        "test.battery.start.deep - Start deep test\n"
        "test.battery.stop - Stop test\n"
    )

    without_credentials = build_ups_discovery_payload(
        _mqtt(),
        _identity(),
        version="0.2.0-alpha",
        snapshot=None,
        capabilities=caps,
    )["components"]
    assert "capabilities" in without_credentials
    assert "test_quick" not in without_credentials
    assert "test_deep" not in without_credentials
    assert "test_stop" not in without_credentials

    with_credentials = build_ups_discovery_payload(
        _mqtt(),
        _identity(),
        version="0.2.0-alpha",
        snapshot=None,
        capabilities=caps,
        controls_enabled=True,
    )["components"]
    assert "test_quick" in with_credentials
    assert "test_deep" in with_credentials
    assert "test_stop" in with_credentials
