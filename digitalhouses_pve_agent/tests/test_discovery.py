from app.config import AppConfig, GeneralConfig, MqttConfig
from app.discovery import build_discovery_payload
from app.identity import HostIdentity
from app.runtime_settings import SETTING_SPECS


def _config() -> AppConfig:
    return AppConfig(
        general=GeneralConfig(instance_id="", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(
            host="192.168.11.33",
            port=1883,
            username="u",
            password="p",
            topic_prefix="DigitalHouses/Global/dh_pve_app",
            discovery_prefix="homeassistant",
            keepalive_seconds=60,
        ),
    )


def _identity() -> HostIdentity:
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="0123456789abcdef0123456789abcdef",
        hostname="pve",
        node_name="PVE",
    )


def test_discovery_uses_canonical_dh_app_pve_device_and_refresh_contract():
    payload = build_discovery_payload(_config(), _identity(), version="0.1.0")
    components = payload["components"]

    canonical_id = "dh_app_pve_0123456789abcdef0123456789abcdef"
    assert payload["device"]["name"] == "DH PVE"
    assert payload["device"]["identifiers"] == [canonical_id]
    assert components["refresh"]["unique_id"] == f"{canonical_id}_refresh"
    assert components["refresh"]["default_entity_id"] == "button.dh_app_pve_refresh"
    assert components["refresh"]["command_topic"] == (
        "DigitalHouses/Global/dh_pve_app/"
        "0123456789abcdef0123456789abcdef/refresh"
    )
    assert components["refresh"]["payload_press"] == "PRESS"
    assert components["last_refresh"]["default_entity_id"] == "sensor.dh_app_pve_last_refresh"
    assert components["last_refresh"]["device_class"] == "timestamp"


def test_discovery_exposes_only_app_owned_alert_threshold_numbers():
    payload = build_discovery_payload(_config(), _identity(), version="0.1.0")
    components = payload["components"]

    setting_components = {
        key.removeprefix("setting_"): value
        for key, value in components.items()
        if key.startswith("setting_")
    }
    assert set(setting_components) == set(SETTING_SPECS)
    assert set(setting_components) == {
        "storage_percent_used_threshold",
        "cpu_temperature_threshold",
        "hdd_temperature_threshold",
        "ssd_temperature_threshold",
        "nvme_temperature_threshold",
        "gpu_temperature_threshold",
    }

    base = "DigitalHouses/Global/dh_pve_app/0123456789abcdef0123456789abcdef/settings"
    for key, spec in SETTING_SPECS.items():
        component = setting_components[key]
        assert component["platform"] == "number"
        assert component["entity_category"] == "config"
        assert component["default_entity_id"] == spec.entity_id
        assert component["min"] == spec.minimum
        assert component["max"] == spec.maximum
        assert component["step"] == spec.step
        assert component["unit_of_measurement"] == spec.unit
        assert component["state_topic"] == f"{base}/{key}/state"
        assert component["command_topic"] == f"{base}/{key}/set"


def test_discovery_does_not_expose_collection_cadence_or_publish_delta_controls():
    payload = build_discovery_payload(_config(), _identity(), version="0.1.0")
    components = payload["components"]

    assert "setting_fast_poll_interval_seconds" not in components
    assert "setting_disk_poll_interval_seconds" not in components
    assert not any("publish_delta" in key for key in components)
