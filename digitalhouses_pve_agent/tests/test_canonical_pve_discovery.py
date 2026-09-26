from app.config import AppConfig, GeneralConfig, MqttConfig
from app.identity import HostIdentity
from app.shutdown_discovery import build_shutdown_aware_pve_discovery_payload
from app.topics import build_topics


def _config():
    return AppConfig(
        general=GeneralConfig(instance_id="", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(
            host="mqtt",
            port=1883,
            username="",
            password="",
            topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
            discovery_prefix="homeassistant",
            keepalive_seconds=60,
        ),
    )


def _identity():
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )


def _inventory():
    return {
        "storage": {
            "local-lvm": {
                "name": "local-lvm",
                "storage_type": "lvmthin",
                "status": "active",
                "usage_percent": 81.0,
            }
        },
        "smart": {
            "nvme_hot": {
                "disk_id": "nvme_hot",
                "model": "NVMe Test",
                "serial": "SERIAL",
                "disk_type": "NVMe",
                "device_path": "/dev/nvme0",
                "available": True,
                "smart_passed": True,
                "health_state": "HEALTHY",
                "temperature_c": 55.0,
                "wear_used_percent": 3.0,
            }
        },
        "gpu": {
            "pci_0000_00_02_0": {
                "display_name": "Intel UHD",
                "model": "Intel UHD",
                "vendor_id": "0x8086",
                "pci_address": "0000:00:02.0",
                "temperature_c": 52.0,
                "transcoding_load_percent": 25.0,
            }
        },
        "fans": {
            "cpu_fan": {
                "display_name": "CPU fan",
                "label": "CPU fan",
                "chip": "nct6798",
                "rpm": 1200,
            }
        },
        "guests": {"vms": {}, "lxcs": {}, "summary": {}},
        "topology": {"assignments": {}},
    }


def _payload():
    return build_shutdown_aware_pve_discovery_payload(
        _config(), _identity(), version="0.3.0", inventory=_inventory()
    )


def test_canonical_pve_device_identity_and_discovery_topic():
    topics = build_topics(_config().mqtt, _identity())
    payload = _payload()

    assert topics.device_id == "dh_pve_agent_node_a"
    assert topics.discovery == "homeassistant/device/dh_pve_agent_node_a/config"
    assert payload["device"]["identifiers"] == ["dh_pve_agent_node_a"]
    assert all(
        component["unique_id"].startswith("dh_pve_agent_node_a_")
        for component in payload["components"].values()
        if "unique_id" in component
    )


def test_canonical_pve_telemetry_ids_and_percent_used_naming():
    c = _payload()["components"]

    assert c["cpu_usage"]["default_entity_id"] == "sensor.dh_pve_agent_cpu_usage"
    assert c["cpu_temperature"]["default_entity_id"] == "sensor.dh_pve_agent_cpu_temperature"
    assert c["cpu_frequency"]["default_entity_id"] == "sensor.dh_pve_agent_cpu_frequency"
    assert c["memory_usage"]["default_entity_id"] == "sensor.dh_pve_agent_memory_usage"
    assert c["swap_usage"]["default_entity_id"] == "sensor.dh_pve_agent_swap_usage"

    storage = c["storage_local_lvm_percent_used"]
    assert storage["default_entity_id"] == "sensor.dh_pve_agent_storage_local_lvm_percent_used"
    assert "usage_percent" in storage["value_template"]
    assert "storage_local_lvm_usage" not in c

    assert c["disk_nvme_hot_temperature"]["default_entity_id"] == (
        "sensor.dh_pve_agent_disk_nvme_hot_temperature"
    )
    assert c["disk_nvme_hot_wear"]["default_entity_id"] == (
        "sensor.dh_pve_agent_disk_nvme_hot_wear"
    )
    assert c["gpu_pci_0000_00_02_0_temperature"]["default_entity_id"] == (
        "sensor.dh_pve_agent_gpu_pci_0000_00_02_0_temperature"
    )
    assert c["gpu_pci_0000_00_02_0_transcoding"]["default_entity_id"] == (
        "sensor.dh_pve_agent_gpu_pci_0000_00_02_0_transcoding"
    )
    assert c["fan_cpu_fan_rpm"]["default_entity_id"] == "sensor.dh_pve_agent_fan_cpu_fan_rpm"

    for component in c.values():
        entity_id = component.get("default_entity_id", "")
        assert ".dh_app_pve_" not in entity_id
        assert ".dh_pve_" not in entity_id.replace(".dh_pve_agent_", ".canonical_")


def test_problem_binaries_use_app_owned_retained_problem_topics():
    topics = build_topics(_config().mqtt, _identity())
    c = _payload()["components"]
    expected = {
        "cpu_temperature_problem": (
            "binary_sensor.dh_pve_agent_cpu_temperature_problem",
            "cpu_temperature",
        ),
        "cpu_throttling_problem": (
            "binary_sensor.dh_pve_agent_cpu_throttling_problem",
            "cpu_throttling",
        ),
        "storage_local_lvm_percent_used_problem": (
            "binary_sensor.dh_pve_agent_storage_local_lvm_percent_used_problem",
            "storage_local_lvm_percent_used",
        ),
        "disk_nvme_hot_temperature_problem": (
            "binary_sensor.dh_pve_agent_disk_nvme_hot_temperature_problem",
            "disk_nvme_hot_temperature",
        ),
        "disk_nvme_hot_smart_problem": (
            "binary_sensor.dh_pve_agent_disk_nvme_hot_smart_problem",
            "disk_nvme_hot_smart",
        ),
        "gpu_pci_0000_00_02_0_temperature_problem": (
            "binary_sensor.dh_pve_agent_gpu_pci_0000_00_02_0_temperature_problem",
            "gpu_pci_0000_00_02_0_temperature",
        ),
    }

    for key, (entity_id, problem_id) in expected.items():
        component = c[key]
        assert component["platform"] == "binary_sensor"
        assert component["default_entity_id"] == entity_id
        assert component["state_topic"] == f"{topics.base}/problems/{problem_id}/state"
        assert component["payload_on"] == "ON"
        assert component["payload_off"] == "OFF"
        assert component["device_class"] == "problem"
        assert component["entity_category"] == "diagnostic"

    assert "cpu_throttling" not in c


def test_problem_aggregate_and_native_mqtt_event_are_canonical():
    topics = build_topics(_config().mqtt, _identity())
    c = _payload()["components"]

    aggregate = c["problems"]
    assert aggregate["platform"] == "sensor"
    assert aggregate["default_entity_id"] == "sensor.dh_pve_agent_problems"
    assert aggregate["state_topic"] == f"{topics.base}/problems/aggregate"
    assert aggregate["json_attributes_topic"] == f"{topics.base}/problems/presentation"
    assert aggregate["entity_category"] == "diagnostic"

    event = c["diagnostic_event"]
    assert event["platform"] == "event"
    assert event["default_entity_id"] == "event.dh_pve_agent_diagnostic"
    assert event["state_topic"] == topics.diagnostic_event
    assert event["event_types"] == [
        "cpu_temperature_high",
        "cpu_temperature_normal",
        "cpu_throttling_started",
        "cpu_throttling_cleared",
        "storage_usage_high",
        "storage_usage_normal",
        "disk_temperature_high",
        "disk_temperature_normal",
        "gpu_temperature_high",
        "gpu_temperature_normal",
        "fan_control_restore_failed",
        "fan_control_restored",
        "disk_smart_failed",
        "disk_smart_restored",
    ]
    assert event["qos"] == 1
    assert event["entity_category"] == "diagnostic"
    assert "json_attributes_topic" not in event


def test_fan_discovery_uses_short_sequential_friendly_names():
    inventory = _inventory()
    inventory["fans"] = {
        "candidate_count": 2,
        "candidate_ids": [
            "it8613_it87_2608_fan2",
            "it8613_it87_2608_fan3",
        ],
        "confirmed_count": 2,
        "count": 2,
        "detected": True,
        "it8613_it87_2608_fan2": {
            "display_name": "it8613 fan2",
            "label": "fan2",
            "chip": "it8613",
            "rpm": 4200,
            "speed_percent": 77.0,
            "max_rpm": 5450,
            "calibration_status": "calibrated",
            "calibrated_at": "2026-09-23T00:00:00+00:00",
        },
        "it8613_it87_2608_fan3": {
            "display_name": "it8613 fan3",
            "label": "fan3",
            "chip": "it8613",
            "rpm": 3200,
            "speed_percent": 59.0,
            "max_rpm": 5400,
            "calibration_status": "calibrated",
            "calibrated_at": "2026-09-23T00:00:00+00:00",
        },
        "status": "Detected",
        "unconfirmed_count": 0,
    }
    components = build_shutdown_aware_pve_discovery_payload(
        _config(), _identity(), version="0.5.8", inventory=inventory
    )["components"]

    assert components["fan_it8613_it87_2608_fan2_speed"]["name"] == "Fan 1"
    assert components["fan_it8613_it87_2608_fan2_rpm"]["name"] == "Fan 1 RPM"
    assert components["fan_it8613_it87_2608_fan2_max_rpm"]["name"] == "Fan 1 Max RPM"
    assert (
        components["fan_it8613_it87_2608_fan2_calibration_status"]["name"]
        == "Fan 1 Calibration status"
    )
    assert (
        components["fan_it8613_it87_2608_fan2_calibrated_at"]["name"]
        == "Fan 1 Calibrated at"
    )

    assert components["fan_it8613_it87_2608_fan3_speed"]["name"] == "Fan 2"
    assert components["fan_it8613_it87_2608_fan3_rpm"]["name"] == "Fan 2 RPM"

    assert components["fan_it8613_it87_2608_fan2_speed"]["default_entity_id"] == (
        "sensor.dh_pve_agent_fan_it8613_it87_2608_fan2_speed"
    )
    assert components["fan_it8613_it87_2608_fan3_speed"]["default_entity_id"] == (
        "sensor.dh_pve_agent_fan_it8613_it87_2608_fan3_speed"
    )
