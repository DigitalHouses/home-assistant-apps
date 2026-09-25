from app.config import AppConfig, GeneralConfig, MqttConfig
from app.identity import HostIdentity
from app.shutdown_discovery import build_shutdown_aware_pve_discovery_payload
from app.topics import build_topics, state_group_topic


def test_disk_temperature_uses_status_topic_for_object_availability():
    config = AppConfig(
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
    identity = HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="0123456789abcdef0123456789abcdef",
        hostname="pve",
        node_name="PVE",
    )
    inventory = {
        "smart": {
            "disk0": {
                "disk_id": "disk0",
                "disk_type": "NVMe",
                "model": "Test NVMe",
                "serial": "TEST123",
                "device_path": "/dev/nvme0",
                "available": True,
                "smart_passed": True,
                "health_state": "HEALTHY",
                "health_reasons": [],
                "recommendation": None,
                "temperature_c": 57.0,
            }
        }
    }
    topics = build_topics(config.mqtt, identity)
    component = build_shutdown_aware_pve_discovery_payload(
        config, identity, version="0.3.0", inventory=inventory
    )["components"]["disk_disk0_temperature"]

    assert component["state_topic"] == state_group_topic(
        topics, "disk/disk0/telemetry"
    )

    object_availability = next(
        entry
        for entry in component["availability"]
        if "subsystems.smart.data" in entry.get("value_template", "")
    )
    assert object_availability["topic"] == state_group_topic(
        topics, "disk/disk0/status"
    )
