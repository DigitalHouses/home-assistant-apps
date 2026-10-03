import subprocess
from types import SimpleNamespace

from app.config import MqttConfig, UpsConfig
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity
from app.ups_control import (
    list_ups_commands,
    parse_upscmd_list_output,
    run_ups_battery_test,
)


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


def _components(caps):
    return build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.5.52",
        snapshot=None, capabilities=caps,
    )["components"]


def test_snmp_standard_only_is_not_assumed_quick_or_deep():
    caps = parse_upscmd_list_output(
        "test.battery.start - Start a battery test\n"
        "calibrate.start - Start runtime calibration\n"
        "shutdown.return - Turn off UPS\n"
    )
    assert caps.battery_tests == ("standard",)
    assert caps.supports_test("standard")
    assert not caps.supports_test("quick")
    assert not caps.supports_test("deep")
    components = _components(caps)
    assert "test_standard" in components
    assert "test_quick" not in components
    assert "test_deep" not in components
    assert "test_stop" not in components
    assert components["test_standard"]["command_topic"].endswith("/ups/test/standard")
    assert components["standard_test_supported"]["default_entity_id"] == (
        "binary_sensor.dh_pve_agent_ups_standard_test_supported"
    )
    assert components["standard_test_supported"]["entity_category"] == "diagnostic"


def test_ietf_separate_commands_remain_separate():
    caps = parse_upscmd_list_output(
        "test.battery.start - General systems test\n"
        "test.battery.start.quick - Quick battery test\n"
        "test.battery.start.deep - Deep calibration\n"
        "test.battery.stop - Abort test\n"
    )
    assert caps.battery_tests == ("standard", "quick", "deep", "stop")
    for key in ("test_standard", "test_quick", "test_deep", "test_stop"):
        assert key in _components(caps)


def test_standard_button_requires_nut_credentials():
    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout="test.battery.start - Battery test\n", stderr="",
        )

    caps = list_ups_commands(UpsConfig(name="ups"), runner=runner)
    assert caps.commands == ("test.battery.start",)
    assert not caps.supports_test("standard")
    assert "test_standard" not in _components(caps)
    assert caps.as_dict()["standard_test_supported"] is False

    caps = list_ups_commands(
        UpsConfig(name="ups", command_username="operator", command_password="secret"),
        runner=runner,
    )
    assert caps.supports_test("standard")
    assert caps.as_dict()["standard_test_supported"] is True
    assert "test_standard" in _components(caps)


def test_executor_uses_only_allowlisted_standard_command():
    observed = []

    def runner(cmd, **kwargs):
        observed.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    config = SimpleNamespace(
        name="ups", host="127.0.0.1", port=3493,
        command_username="operator", command_password="hidden",
        command_timeout_seconds=3,
    )
    run_ups_battery_test(config, "standard", runner=runner)
    assert observed[0][0][-1] == "test.battery.start"
    assert observed[0][1]["check"] is True
    assert observed[0][1]["timeout"] == 3
