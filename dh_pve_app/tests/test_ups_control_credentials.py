import subprocess

from app.config import MqttConfig, UpsConfig
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity
from app.ups_control import list_ups_commands


COMMANDS = (
    "test.battery.start.quick - Start quick test\n"
    "test.battery.start.deep - Start deep test\n"
    "test.battery.stop - Stop test\n"
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


def _runner(command, **kwargs):
    return subprocess.CompletedProcess(command, 0, stdout=COMMANDS, stderr="")


def test_battery_test_buttons_require_both_capability_and_command_credentials():
    without_credentials = list_ups_commands(
        UpsConfig(name="ups"),
        runner=_runner,
    )
    components = build_ups_discovery_payload(
        _mqtt(),
        _identity(),
        version="0.2.0-alpha",
        snapshot=None,
        capabilities=without_credentials,
    )["components"]
    assert "capabilities" in components
    assert "test_quick" not in components
    assert "test_deep" not in components
    assert "test_stop" not in components

    with_credentials = list_ups_commands(
        UpsConfig(
            name="ups",
            command_username="dh_pve_app",
            command_password="secret",
        ),
        runner=_runner,
    )
    components = build_ups_discovery_payload(
        _mqtt(),
        _identity(),
        version="0.2.0-alpha",
        snapshot=None,
        capabilities=with_credentials,
    )["components"]
    assert "test_quick" in components
    assert "test_deep" in components
    assert "test_stop" in components
