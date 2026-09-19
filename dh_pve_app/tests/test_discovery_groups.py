from app.config import AppConfig, GeneralConfig, MqttConfig
from app.identity import HostIdentity
from app.shutdown_discovery import build_shutdown_aware_pve_discovery_payload
from app.topics import build_topics, state_group_topic


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


def _inventory():
    return {
        "storage": {
            "local-lvm": {
                "storage_type": "lvmthin",
                "status": "active",
                "used_gib": 350.0,
                "total_gib": 800.0,
                "usage_percent": 43.75,
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
                "health_reasons": [],
                "recommendation": None,
                "temperature_c": 55.0,
                "wear_used_percent": 3.0,
                "unsafe_shutdowns": 2,
            }
        },
        "gpu": {
            "pci_0000_00_02_0": {
                "display_name": "Intel UHD",
                "model": "Intel UHD",
                "vendor_id": "0x8086",
                "pci_address": "0000:00:02.0",
                "owner": "VM 501",
                "temperature_c": 52.0,
                "transcoding_load_percent": 25.0,
            }
        },
        "fans": {
            "nct6798_fan1": {
                "display_name": "CPU fan",
                "label": "CPU fan",
                "chip": "nct6798",
                "rpm": 1200,
            }
        },
        "guests": {
            "vms": {
                "501": {
                    "kind": "vm",
                    "guest_id": "501",
                    "name": "plex",
                    "status": "running",
                    "qemu_agent": "available",
                    "passthrough_count": 1,
                }
            },
            "lxcs": {},
            "summary": {
                "vms": {"total": 1, "running": 1, "paused": 0, "stopped": 0, "unknown": 0},
                "lxcs": {"total": 0, "running": 0, "paused": 0, "stopped": 0, "unknown": 0},
            },
        },
        "topology": {
            "assignments": {
                "pci_0000_00_02_0": {
                    "connection": "passthrough_pci",
                    "owner_kind": "vm",
                    "owner_id": "501",
                    "owner_name": "plex",
                    "config_key": "hostpci0",
                    "pci_address": "0000:00:02.0",
                    "pci_class": "0300",
                    "class_name": "VGA compatible controller",
                    "model": "Intel UHD",
                }
            }
        },
    }


def _payload():
    return build_shutdown_aware_pve_discovery_payload(
        _config(), _identity(), version="0.5.1", inventory=_inventory()
    )


def _components():
    return _payload()["components"]


def test_pve_discovery_routes_entities_to_smallest_state_group():
    topics = build_topics(_config().mqtt, _identity())
    c = _components()

    assert c["system"]["state_topic"] == state_group_topic(topics, "host")
    assert c["previous_shutdown"]["state_topic"] == state_group_topic(topics, "shutdown")
    assert c["cpu_usage"]["state_topic"] == state_group_topic(topics, "cpu")
    assert c["memory_usage"]["state_topic"] == state_group_topic(topics, "memory")
    assert c["storage_local_lvm_percent_used"]["state_topic"] == state_group_topic(
        topics, "storage/local-lvm"
    )
    assert c["disk_nvme_hot_temperature"]["state_topic"] == state_group_topic(
        topics, "disk/nvme_hot/telemetry"
    )
    assert c["disk_nvme_hot_health"]["state_topic"] == state_group_topic(
        topics, "disk/nvme_hot/status"
    )
    assert c["gpu_pci_0000_00_02_0_temperature"]["state_topic"] == state_group_topic(
        topics, "gpu/pci_0000_00_02_0/telemetry"
    )
    assert c["gpu_pci_0000_00_02_0_owner"]["state_topic"] == state_group_topic(
        topics, "gpu/pci_0000_00_02_0/status"
    )
    assert c["fan_nct6798_fan1_rpm"]["state_topic"] == state_group_topic(
        topics, "fan/nct6798_fan1"
    )
    assert c["vm_501_status"]["state_topic"] == state_group_topic(
        topics, "guest/vm/501"
    )
    assert c["vms_summary"]["state_topic"] == state_group_topic(topics, "guest/summary")
    assert c["passthrough_pci_0000_00_02_0"]["state_topic"] == state_group_topic(
        topics, "topology"
    )
    assert c["collector_cpu"]["state_topic"] == state_group_topic(
        topics, "collector/cpu"
    )


def test_unconfirmed_fan_candidate_is_omitted_not_tombstoned():
    inventory = _inventory()
    inventory["fans"] = {
        "detected": True,
        "count": 1,
        "candidate_count": 2,
        "confirmed_count": 1,
        "unconfirmed_count": 1,
        "candidate_ids": [
            "it8613_it87_2608_fan2",
            "it8613_it87_2608_fan3",
        ],
        "it8613_it87_2608_fan2": {
            "fan_id": "it8613_it87_2608_fan2",
            "display_name": "Fan 2 RPM - it8613",
            "label": "Fan 2",
            "chip": "it8613",
            "rpm": 3792,
        },
    }

    components = build_shutdown_aware_pve_discovery_payload(
        _config(), _identity(), version="0.5.6", inventory=inventory
    )["components"]

    assert "fan_it8613_it87_2608_fan2_rpm" in components
    assert "fan_it8613_it87_2608_fan3_rpm" not in components


def test_first_positive_fan_debounce_does_not_emit_tombstone():
    inventory = _inventory()
    inventory["fans"] = {
        "detected": False,
        "count": 0,
        "candidate_count": 2,
        "confirmed_count": 0,
        "unconfirmed_count": 2,
        "candidate_ids": [
            "it8613_it87_2608_fan2",
            "it8613_it87_2608_fan3",
        ],
    }

    components = build_shutdown_aware_pve_discovery_payload(
        _config(), _identity(), version="0.5.6", inventory=inventory
    )["components"]

    assert "fan_it8613_it87_2608_fan2_rpm" not in components
    assert "fan_it8613_it87_2608_fan3_rpm" not in components


def test_pve_discovery_exposes_presentation_diagnostics():
    topics = build_topics(_config().mqtt, _identity())
    c = _components()
    diagnostics = state_group_topic(topics, "diagnostics")

    assert c["app_profile"]["default_entity_id"] == "sensor.dh_app_pve_app_profile"
    assert c["app_profile"]["state_topic"] == diagnostics
    assert "app_profile.state" in c["app_profile"]["value_template"]
    assert "resources" in c["app_profile"]["json_attributes_template"]

    assert c["last_publication"]["default_entity_id"] == "sensor.dh_app_pve_last_publication"
    assert c["last_publication"]["state_topic"] == diagnostics
    assert c["last_publication"]["device_class"] == "timestamp"
    assert "last_publication.timestamp" in c["last_publication"]["value_template"]

    assert c["last_refresh"]["state_topic"] == diagnostics


def test_pve_discovery_exposes_app_version_from_same_release_value():
    topics = build_topics(_config().mqtt, _identity())
    payload = _payload()
    c = payload["components"]
    diagnostics = state_group_topic(topics, "diagnostics")

    assert [key for key in c if key == "app_version"] == ["app_version"]
    assert c["app_version"]["platform"] == "sensor"
    assert c["app_version"]["default_entity_id"] == "sensor.dh_app_pve_app_version"
    assert c["app_version"]["state_topic"] == diagnostics
    assert c["app_version"]["value_template"] == (
        "{{ value_json.app_version | default('unknown') }}"
    )
    assert c["app_version"]["entity_category"] == "diagnostic"
    assert c["app_version"]["icon"] == "mdi:tag-outline"

    assert payload["device"]["name"] == "DH PVE"
    assert payload["device"]["sw_version"] == "0.5.1"
    assert payload["origin"]["sw_version"] == "0.5.1"


def test_continuous_sensor_attributes_do_not_duplicate_volatile_values():
    c = _components()

    memory_attrs = c["memory_usage"]["json_attributes_template"]
    assert "used_gib" not in memory_attrs
    assert "total_gib" in memory_attrs

    storage_attrs = c["storage_local_lvm_percent_used"]["json_attributes_template"]
    assert "used_gib" not in storage_attrs
    assert '"status"' not in storage_attrs
    assert "total_gib" in storage_attrs
    assert "storage_type" in storage_attrs
