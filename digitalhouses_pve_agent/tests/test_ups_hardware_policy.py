from app.config import MqttConfig
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity
from app.ups_nut import parse_upsc_output, ups_metrics


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
        "\n".join(
            (
                "ups.status: OL",
                "battery.runtime.low: 600",
                "battery.charge.low: 10",
                "battery.charge.warning: 20",
                "ups.delay.shutdown: 60",
                "ups.delay.start: 120",
            )
        )
    )


def test_upsc_parser_keeps_hardware_shutdown_and_restore_delays_read_only():
    snapshot = _snapshot()

    assert snapshot.low_runtime_seconds == 600
    assert snapshot.low_charge_percent == 10
    assert snapshot.warning_charge_percent == 20
    assert snapshot.ups_shutdown_delay_seconds == 60
    assert snapshot.ups_start_delay_seconds == 120

    metrics = ups_metrics(snapshot)
    assert metrics["ups_shutdown_delay_seconds"].value == 60
    assert metrics["ups_start_delay_seconds"].value == 120
    assert metrics["ups_shutdown_delay_seconds"].policy == "discrete"
    assert metrics["ups_start_delay_seconds"].policy == "discrete"


def test_discovery_exposes_actual_ups_protection_values_as_diagnostic_sensors():
    payload = build_ups_discovery_payload(
        _mqtt(),
        _identity(),
        version="0.2.0-alpha",
        snapshot=_snapshot(),
    )
    components = payload["components"]

    expected = {
        "battery_runtime_low": (
            "sensor.dh_pve_ups_battery_runtime_low",
            "low_runtime_seconds",
        ),
        "battery_charge_low": (
            "sensor.dh_pve_ups_battery_charge_low",
            "low_charge_percent",
        ),
        "battery_charge_warning": (
            "sensor.dh_pve_ups_battery_charge_warning",
            "warning_charge_percent",
        ),
        "ups_shutdown_delay": (
            "sensor.dh_pve_ups_shutdown_delay",
            "ups_shutdown_delay_seconds",
        ),
        "ups_start_delay": (
            "sensor.dh_pve_ups_start_delay",
            "ups_start_delay_seconds",
        ),
    }

    for key, (entity_id, field) in expected.items():
        component = components[key]
        assert component["platform"] == "sensor"
        assert component["default_entity_id"] == entity_id
        assert field in component["value_template"]
        assert component["entity_category"] == "diagnostic"

    assert components["ups_shutdown_delay"]["unit_of_measurement"] == "s"
    assert components["ups_start_delay"]["unit_of_measurement"] == "s"
