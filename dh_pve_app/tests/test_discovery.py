from app.config import AppConfig, GeneralConfig, MqttConfig
from app.discovery import build_discovery_payload
from app.identity import HostIdentity


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


def test_discovery_uses_dh_pve_device_and_refresh_contract():
    payload = build_discovery_payload(_config(), _identity(), version="0.1.0")
    components = payload["components"]

    assert payload["device"]["name"] == "DH PVE"
    assert payload["device"]["identifiers"] == ["dh_pve_0123456789abcdef0123456789abcdef"]
    assert components["refresh"]["default_entity_id"] == "button.dh_pve_refresh"
    assert components["refresh"]["command_topic"] == (
        "DigitalHouses/Global/dh_pve_app/"
        "0123456789abcdef0123456789abcdef/refresh"
    )
    assert components["refresh"]["payload_press"] == "PRESS"
    assert components["last_refresh"]["default_entity_id"] == "sensor.dh_pve_last_refresh"
    assert components["last_refresh"]["device_class"] == "timestamp"


def test_discovery_exposes_only_bounded_collector_runtime_numbers():
    payload = build_discovery_payload(_config(), _identity(), version="0.1.0")
    components = payload["components"]
    fast = components["setting_fast_poll_interval_seconds"]
    disk = components["setting_disk_poll_interval_seconds"]

    assert fast["platform"] == "number"
    assert fast["default_entity_id"] == "number.dh_pve_fast_poll_interval"
    assert fast["command_topic"].endswith("/settings/fast_poll_interval_seconds/set")
    assert fast["state_topic"].endswith("/settings/fast_poll_interval_seconds/state")
    assert fast["min"] == 2.0
    assert fast["max"] == 60.0
    assert fast["entity_category"] == "config"
    assert disk["default_entity_id"] == "number.dh_pve_disk_poll_interval"
    assert not any("publish_delta" in key for key in components)
