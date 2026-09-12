from pathlib import Path

from app.config import MqttConfig
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity
from app.topics import build_topics, build_ups_topics
from app.ups_nut import parse_upsc_output

FIX = Path(__file__).parent / "fixtures" / "ups" / "cyberpower_ut2200e.upsc"


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


def test_ups_topics_are_separate_from_pve_topics():
    pve = build_topics(_mqtt(), _identity())
    ups = build_ups_topics(_mqtt(), _identity())

    assert ups.state == f"{pve.base}/ups/state"
    assert ups.availability == f"{pve.base}/ups/availability"
    assert ups.refresh == f"{pve.base}/ups/refresh"
    assert ups.discovery == "homeassistant/device/dh_pve_ups_node_a/config"
    assert ups.legacy_discovery == "homeassistant/device/dh_ups_node_a/config"
    assert ups.device_id == "dh_pve_ups_node_a"
    assert pve.state != ups.state
    assert pve.discovery != ups.discovery


def test_discovery_only_creates_supported_factual_entities():
    snapshot = parse_upsc_output(FIX.read_text(encoding="utf-8"))
    payload = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=snapshot
    )
    components = payload["components"]

    assert "status" in components
    assert "problems" in components
    assert "available" in components
    assert "refresh" in components
    assert "last_refresh" in components
    assert "battery_charge" in components
    assert "battery_runtime_minutes" in components
    assert "battery_runtime" in components
    assert "battery_voltage" in components
    assert "load" in components
    assert "nominal_real_power" in components
    assert "estimated_real_power" not in components
    assert "input_voltage" in components
    assert "output_voltage" in components
    assert "unsupported_temperature" not in components


def test_problems_sensor_remains_available_when_nut_read_fails():
    payload = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=None
    )
    problems = payload["components"]["problems"]

    assert problems["default_entity_id"] == "sensor.dh_pve_ups_problems"
    assert problems["value_template"] == "{{ value_json.problems_count | default(0) }}"
    assert len(problems["availability"]) == 1
    assert "value_json.available" not in str(problems["availability"])
    assert "problems_severity" in problems["json_attributes_template"]
    assert "problems_details" in problems["json_attributes_template"]
    assert "problems" in problems["json_attributes_template"]


def test_primary_ups_entities_stay_out_of_diagnostics():
    snapshot = parse_upsc_output(FIX.read_text(encoding="utf-8"))
    components = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=snapshot
    )["components"]

    for key in (
        "status",
        "problems",
        "battery_charge",
        "battery_runtime_minutes",
        "load",
        "input_voltage",
        "output_voltage",
        "on_battery",
        "low_battery",
        "replace_battery",
        "overload",
        "bypass",
    ):
        assert components[key].get("entity_category") is None


def test_service_ups_entities_are_diagnostic():
    snapshot = parse_upsc_output(FIX.read_text(encoding="utf-8"))
    components = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=snapshot
    )["components"]

    for key in (
        "available",
        "last_refresh",
        "refresh",
        "battery_runtime",
        "battery_voltage",
        "nominal_real_power",
        "battery_charge_warning",
        "battery_charge_low",
        "battery_runtime_low",
        "test_result",
        "beeper_status",
        "charging",
        "discharging",
    ):
        assert components[key]["entity_category"] == "diagnostic"


def test_discovery_omits_capability_not_reported_by_ups():
    snapshot = parse_upsc_output("ups.status: OL\ndevice.model: Minimal\n")
    payload = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=snapshot
    )
    components = payload["components"]

    assert "status" in components
    assert "problems" in components
    assert "battery_charge" not in components
    assert "battery_runtime_minutes" not in components
    assert "battery_runtime" not in components
    assert "input_voltage" not in components


def test_ups_device_metadata_uses_real_hardware_identity():
    snapshot = parse_upsc_output(FIX.read_text(encoding="utf-8"))
    payload = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=snapshot
    )

    assert payload["device"]["identifiers"] == ["dh_pve_ups_node_a"]
    assert payload["device"]["name"] == "DH PVE UPS"
    assert payload["device"]["manufacturer"] == "CPS"
    assert payload["device"]["model"] == "UT2200E"
    assert payload["origin"]["name"] == "DigitalHouses DH PVE App"


def test_ups_telemetry_uses_app_and_nut_availability_without_nut_abbreviations():
    snapshot = parse_upsc_output(FIX.read_text(encoding="utf-8"))
    payload = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=snapshot
    )
    status = payload["components"]["status"]
    available = payload["components"]["available"]

    assert len(status["availability"]) == 2
    assert "value_json.available" in status["availability"][1]["value_template"]
    assert len(available["availability"]) == 1
    assert "OL" not in status["value_template"]
    assert "value_json.status" in status["value_template"]
