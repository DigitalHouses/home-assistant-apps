from app.config import MqttConfig
from app.identity import HostIdentity
from app.shutdown_discovery import build_shutdown_aware_ups_discovery_payload
from app.topics import build_ups_topics, ups_state_group_topic
from app.ups_nut import parse_upsc_output


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


def _snapshot():
    return parse_upsc_output(
        "device.mfr: CPS\n"
        "device.model: UT2200E\n"
        "device.serial: TEST123\n"
        "ups.status: OL\n"
        "battery.charge: 100\n"
        "battery.runtime: 2160\n"
        "battery.voltage: 27\n"
        "battery.voltage.nominal: 24\n"
        "ups.load: 5\n"
        "ups.realpower.nominal: 1320\n"
        "input.voltage: 220\n"
        "output.voltage: 220\n"
        "input.frequency: 50\n"
        "output.frequency: 50\n"
        "battery.charge.warning: 20\n"
        "battery.charge.low: 10\n"
        "battery.runtime.low: 300\n"
        "ups.delay.shutdown: 20\n"
        "ups.delay.start: 120\n"
        "ups.test.result: No test initiated\n"
        "ups.beeper.status: enabled\n"
    )


def _components():
    return build_shutdown_aware_ups_discovery_payload(
        _mqtt(),
        _identity(),
        version="0.2.0",
        snapshot=_snapshot(),
        capabilities=None,
        shutdown_policy=None,
    )["components"]


def test_ups_discovery_routes_entities_to_independent_state_groups():
    topics = build_ups_topics(_mqtt(), _identity())
    c = _components()

    telemetry = ups_state_group_topic(topics, "telemetry")
    status = ups_state_group_topic(topics, "status")
    config = ups_state_group_topic(topics, "config")
    tests = ups_state_group_topic(topics, "tests")
    diagnostics = ups_state_group_topic(topics, "diagnostics")

    for key in (
        "battery_charge",
        "battery_runtime_minutes",
        "battery_runtime",
        "battery_voltage",
        "load",
        "input_voltage",
        "output_voltage",
        "input_frequency",
        "output_frequency",
    ):
        assert c[key]["state_topic"] == telemetry

    for key in (
        "status",
        "problems",
        "available",
        "on_battery",
        "low_battery",
        "replace_battery",
        "overload",
        "bypass",
        "charging",
        "discharging",
    ):
        assert c[key]["state_topic"] == status

    for key in (
        "capabilities",
        "shutdown_policy",
        "policy_on_battery_delay_observed",
        "policy_power_restore_delay_observed",
        "nominal_real_power",
        "battery_charge_warning",
        "battery_charge_low",
        "battery_runtime_low",
        "ups_shutdown_delay",
        "ups_start_delay",
        "guest_shutdown_budget",
    ):
        assert c[key]["state_topic"] == config

    for key in (
        "test_result",
        "beeper_status",
        "test_quick_interval_days",
        "test_quick_time",
        "test_deep_interval_days",
        "test_deep_time",
        "test_state",
        "last_quick_test",
        "next_quick_test",
        "last_deep_test",
        "next_deep_test",
        "test_history",
    ):
        assert c[key]["state_topic"] == tests

    assert c["last_refresh"]["state_topic"] == diagnostics
    assert c["shutdown_readiness"]["state_topic"] == diagnostics


def test_ups_nut_availability_always_reads_status_group():
    topics = build_ups_topics(_mqtt(), _identity())
    status = ups_state_group_topic(topics, "status")
    c = _components()

    for key in ("battery_charge", "load", "test_result", "battery_charge_low"):
        nut_entries = [
            item
            for item in c[key]["availability"]
            if "value_template" in item and "value_json.available" in item["value_template"]
        ]
        assert len(nut_entries) == 1
        assert nut_entries[0]["topic"] == status
