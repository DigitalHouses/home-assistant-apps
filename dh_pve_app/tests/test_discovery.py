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


def test_discovery_exposes_bounded_runtime_numbers():
    payload = build_discovery_payload(_config(), _identity(), version="0.1.0")
    cpu = payload["components"]["setting_cpu_publish_delta"]

    assert cpu["platform"] == "number"
    assert cpu["default_entity_id"] == "number.dh_pve_cpu_publish_delta"
    assert cpu["command_topic"].endswith("/settings/cpu_publish_delta/set")
    assert cpu["state_topic"].endswith("/settings/cpu_publish_delta/state")
    assert cpu["min"] == 1.0
    assert cpu["max"] == 25.0
    assert cpu["entity_category"] == "config"
    assert cpu["unique_id"].startswith("dh_pve_0123456789abcdef0123456789abcdef_")
