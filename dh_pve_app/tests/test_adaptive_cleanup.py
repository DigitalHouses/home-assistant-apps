from pathlib import Path

from app.config import AppConfig, GeneralConfig, MqttConfig
from app.discovery import build_discovery_payload
from app.identity import HostIdentity
from app.runtime_settings import SETTING_SPECS
from app.shutdown_discovery import build_shutdown_aware_ups_discovery_payload
from app.ups_nut import parse_upsc_output


ROOT = Path(__file__).resolve().parents[1]


def _config():
    return AppConfig(
        general=GeneralConfig(instance_id="", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(
            host="mqtt",
            port=1883,
            username="",
            password="",
            topic_prefix="DigitalHouses/Global/dh_pve_app",
            discovery_prefix="homeassistant",
            keepalive_seconds=60,
        ),
    )


def _identity():
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="0123456789abcdef0123456789abcdef",
        hostname="pve",
        node_name="PVE",
    )


def test_collection_cadence_is_not_exposed_as_runtime_number_settings():
    assert SETTING_SPECS == {}

    components = build_discovery_payload(_config(), _identity(), version="0.2.0")["components"]
    assert "setting_fast_poll_interval_seconds" not in components
    assert "setting_disk_poll_interval_seconds" not in components
    assert not any("publish_delta" in key for key in components)


def test_ha_package_is_recorder_only_without_duplicate_threshold_helpers():
    text = (ROOT / "examples" / "packages" / "dh_app_pve_package.yaml").read_text()

    assert "recorder:" in text
    assert "sensor.dh_pve_*" in text
    assert "binary_sensor.dh_pve_*" in text
    assert "number.dh_pve_ups_*" in text
    assert "time.dh_pve_ups_*" in text
    assert "input_number:" not in text
    assert "automation:" not in text
    assert "_temperature_threshold" not in text
    assert "storage_usage_threshold" not in text


def test_duplicate_ups_runtime_seconds_entity_is_removed_from_discovery():
    snapshot = parse_upsc_output(
        "ups.status: OL\nbattery.runtime: 2160\nbattery.charge: 100\n"
    )
    components = build_shutdown_aware_ups_discovery_payload(
        _config().mqtt,
        _identity(),
        version="0.2.0",
        snapshot=snapshot,
    )["components"]

    assert "battery_runtime_minutes" in components
    assert components["battery_runtime_minutes"]["default_entity_id"] == (
        "sensor.dh_pve_ups_battery_runtime_minutes"
    )
    assert "battery_runtime" not in components
