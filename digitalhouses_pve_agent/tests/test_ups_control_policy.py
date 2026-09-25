import inspect
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import UpsConfig, load_config
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity
from app.mqtt_bridge import MqttEvents
from app.runtime_settings import RuntimeSettings
from app.topics import build_topics, build_ups_topics
from app.config import MqttConfig
from app.ups_runtime import UpsRuntime
import app.ups_nut as ups_nut


UPSCMD_SAMPLE = """Instant commands supported on UPS [ups]:

beeper.disable - Disable the UPS beeper
beeper.enable - Enable the UPS beeper
beeper.mute - Temporarily mute the UPS beeper
beeper.off - Obsolete (use beeper.disable or beeper.mute)
beeper.on - Obsolete (use beeper.enable)
load.off - Turn off the load immediately
load.off.delay - Turn off the load with a delay (seconds)
load.on - Turn on the load immediately
load.on.delay - Turn on the load with a delay (seconds)
shutdown.return - Turn off the load and return when power is back
shutdown.stayoff - Turn off the load and remain off
shutdown.stop - Stop a shutdown in progress
test.battery.start.deep - Start a deep battery test
test.battery.start.quick - Start a quick battery test
test.battery.stop - Stop the battery test
"""

UPSMON_COMMISSIONING = """MONITOR ups@127.0.0.1 1 dh_primary_user dhpassword primary
MINSUPPLIES 1
POLLFREQ 5
POLLFREQALERT 5
DEADTIME 15
NOCOMMWARNTIME 300
HOSTSYNC 120
FINALDELAY 5
SHUTDOWNCMD \"/bin/true\"
"""


def _require(name):
    value = getattr(ups_nut, name, None)
    assert callable(value), f"app.ups_nut.{name} is required"
    return value


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


def test_upscmd_capabilities_are_parsed_and_grouped():
    parser = _require("parse_upscmd_list_output")
    caps = parser(UPSCMD_SAMPLE)

    assert len(caps.commands) == 15
    assert caps.commands[0] == "beeper.disable"
    assert caps.commands[-1] == "test.battery.stop"
    assert caps.battery_tests == ("quick", "deep", "stop")
    assert caps.beeper_control is True
    assert caps.load_control is True
    assert caps.shutdown_control is True
    assert caps.supported_features


def test_upscmd_capability_query_is_read_only_and_bounded():
    reader = _require("list_ups_commands")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=UPSCMD_SAMPLE, stderr="")

    config = UpsConfig(name="ups", host="127.0.0.1", port=3493, command_timeout_seconds=2.5)
    caps = reader(config, runner=runner)

    assert len(caps.commands) == 15
    assert calls == [(
        ["upscmd", "-l", "ups@127.0.0.1:3493"],
        {
            "capture_output": True,
            "text": True,
            "timeout": 2.5,
            "check": True,
        },
    )]


def test_battery_test_executor_maps_only_three_safe_actions_and_hides_password():
    executor = _require("run_ups_battery_test")
    calls = []
    config = SimpleNamespace(
        name="ups",
        host="127.0.0.1",
        port=3493,
        command_timeout_seconds=3.0,
        command_username="dh_pve_app",
        command_password="super-secret",
    )

    def ok_runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="OK\n", stderr="")

    for action, nut_command in (
        ("quick", "test.battery.start.quick"),
        ("deep", "test.battery.start.deep"),
        ("stop", "test.battery.stop"),
    ):
        executor(config, action, runner=ok_runner)
        assert calls[-1][0][-1] == nut_command
        assert calls[-1][0][:5] == ["upscmd", "-u", "dh_pve_app", "-p", "super-secret"]
        assert calls[-1][1]["timeout"] == 3.0
        assert calls[-1][1]["check"] is True

    with pytest.raises(ValueError):
        executor(config, "shutdown.return", runner=ok_runner)

    def failing_runner(command, **kwargs):
        raise subprocess.CalledProcessError(
            1,
            command,
            stderr="authentication failed for super-secret",
        )

    with pytest.raises(Exception) as exc_info:
        executor(config, "quick", runner=failing_runner)
    assert "super-secret" not in str(exc_info.value)


def test_ups_command_credentials_are_optional_private_config(tmp_path: Path):
    assert "command_username" in UpsConfig.__dataclass_fields__
    assert "command_password" in UpsConfig.__dataclass_fields__

    path = tmp_path / "dh_pve_app.conf"
    path.write_text(
        """[mqtt]
host = broker
[ups]
command_username = dh_pve_app
command_password = secret-value
""",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.ups.command_username == "dh_pve_app"
    assert config.ups.command_password == "secret-value"


def test_shutdown_policy_parses_current_commissioning_state():
    parser = _require("parse_shutdown_policy")
    policy = parser(
        UPSMON_COMMISSIONING,
        "CMDSCRIPT /bin/upssched-cmd\n",
        monitor_active=False,
    )

    assert policy.state == "Commissioning"
    assert policy.role == "primary"
    assert policy.nut_monitor == "inactive"
    assert policy.shutdown_enabled is False
    assert policy.shutdown_command == "/bin/true"
    assert policy.min_supplies == 1
    assert policy.pollfreq_seconds == 5
    assert policy.pollfreqalert_seconds == 5
    assert policy.deadtime_seconds == 15
    assert policy.hostsync_seconds == 120
    assert policy.finaldelay_seconds == 5
    assert policy.upssched_present is True
    assert policy.upssched_rules == 0
    assert policy.upssched_active is False
    assert policy.guest_shutdown_budget_seconds is None
    assert policy.power_restore_behavior == "Not configured"
    policy_dict = policy.as_dict()
    assert policy_dict["min_supplies"] == 1
    assert "minsuppplies" not in policy_dict


def test_shutdown_policy_counts_active_upssched_rules_and_enabled_state():
    parser = _require("parse_shutdown_policy")
    policy = parser(
        UPSMON_COMMISSIONING.replace('SHUTDOWNCMD "/bin/true"', 'SHUTDOWNCMD "/sbin/shutdown -h now"'),
        """CMDSCRIPT /bin/upssched-cmd
# AT ONBATT * START-TIMER earlyshutdown 300
AT ONBATT * START-TIMER earlyshutdown 300
AT ONLINE * CANCEL-TIMER earlyshutdown
""",
        monitor_active=True,
        guest_shutdown_budget_seconds=300,
        power_restore_behavior="Full power cycle / restart",
    )

    assert policy.state == "Enabled"
    assert policy.shutdown_enabled is True
    assert policy.upssched_rules == 2
    assert policy.upssched_active is True
    assert policy.guest_shutdown_budget_seconds == 300
    assert policy.power_restore_behavior == "Full power cycle / restart"


def test_ups_topics_and_mqtt_events_cover_battery_test_buttons_statically():
    ups = build_ups_topics(_mqtt(), _identity())
    assert hasattr(ups, "test_quick")
    assert hasattr(ups, "test_deep")
    assert hasattr(ups, "test_stop")

    events = MqttEvents(build_topics(_mqtt(), _identity()), RuntimeSettings())
    events.configure_ups(ups)

    assert events.handle_message(ups.test_quick, b"PRESS") is True
    assert events.ups_test_quick_requested.is_set()
    assert events.handle_message(ups.test_deep, b"PRESS") is True
    assert events.ups_test_deep_requested.is_set()
    assert events.handle_message(ups.test_stop, b"PRESS") is True
    assert events.ups_test_stop_requested.is_set()


def test_discovery_exposes_capability_sensor_policy_sensor_and_supported_test_buttons():
    assert "capabilities" in inspect.signature(build_ups_discovery_payload).parameters
    assert "shutdown_policy" in inspect.signature(build_ups_discovery_payload).parameters

    parser = _require("parse_upscmd_list_output")
    policy_parser = _require("parse_shutdown_policy")
    caps = parser(UPSCMD_SAMPLE)
    policy = policy_parser(UPSMON_COMMISSIONING, "CMDSCRIPT /bin/upssched-cmd\n", monitor_active=False)

    payload = build_ups_discovery_payload(
        _mqtt(),
        _identity(),
        version="0.2.0-alpha",
        snapshot=None,
        capabilities=caps,
        shutdown_policy=policy,
    )
    components = payload["components"]

    assert components["capabilities"]["default_entity_id"] == "sensor.dh_pve_ups_capabilities"
    assert components["shutdown_policy"]["default_entity_id"] == "sensor.dh_pve_ups_shutdown_policy"
    assert components["test_quick"]["default_entity_id"] == "button.dh_pve_ups_test_quick"
    assert components["test_deep"]["default_entity_id"] == "button.dh_pve_ups_test_deep"
    assert components["test_stop"]["default_entity_id"] == "button.dh_pve_ups_test_stop"

    quick_only = parser("test.battery.start.quick - Start a quick battery test\n")
    payload = build_ups_discovery_payload(
        _mqtt(),
        _identity(),
        version="0.2.0-alpha",
        snapshot=None,
        capabilities=quick_only,
        shutdown_policy=policy,
    )
    components = payload["components"]
    assert "test_quick" in components
    assert "test_deep" not in components
    assert "test_stop" not in components


def test_ups_runtime_accepts_control_and_policy_dependencies():
    parameters = inspect.signature(UpsRuntime.__init__).parameters
    assert "capability_reader" in parameters
    assert "command_executor" in parameters
    assert "shutdown_policy_reader" in parameters
