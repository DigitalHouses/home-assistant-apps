from app.config import AppConfig, GeneralConfig, MqttConfig
from app.discovery_guest import build_guest_aware_discovery_payload
from app.discovery_metrics import build_full_discovery_payload
from app.identity import HostIdentity


def _config():
    return AppConfig(
        general=GeneralConfig(instance_id="", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(
            host="mqtt", port=1883, username="", password="",
            topic_prefix="DigitalHouses/Global/dh_pve_app",
            discovery_prefix="homeassistant", keepalive_seconds=60,
        ),
    )


def _identity():
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="0123456789abcdef0123456789abcdef",
        hostname="pve", node_name="PVE",
    )


def _inventory():
    return {
        "storage": {
            "local-lvm": {
                "storage_type": "lvmthin", "status": "active",
                "used_gib": 358.79, "total_gib": 794.30, "usage_percent": 45.17,
            }
        },
        "smart": {
            "wwn_eui_0025382451a05c68": {
                "model": "Samsung SSD 990 EVO 1TB", "serial": "S7M3NL0Y413841D",
                "disk_type": "NVMe", "device_path": "/dev/nvme0", "available": True,
                "smart_passed": True, "health_state": "HEALTHY", "health_reasons": [],
                "recommendation": None, "temperature_c": 57.0, "wear_used_percent": 3.0,
                "power_on_hours": 8938, "media_errors": 0,
                "reallocated_sectors": None, "pending_sectors": None,
                "offline_uncorrectable": None, "unsafe_shutdowns": 25,
                "data_written_tb": 20.7, "daily": {"max_temperature_c": 67.0},
            }
        },
        "gpu": {
            "pci_0000_00_02_0": {
                "display_name": "Intel Alder Lake-N UHD Graphics",
                "model": "Intel Corporation Alder Lake-N [UHD Graphics]",
                "vendor_id": "0x8086", "pci_address": "0000:00:02.0",
                "kernel_driver": "vfio-pci", "owner": "VM 501",
                "connection": "passthrough_pci", "source_type": "vm",
                "source_id": "501", "source_name": "plex-vm",
                "temperature_c": None, "transcoding_load_percent": 33.2,
            }
        },
        "fans": {
            "nct6798_isa_0290_fan1": {
                "display_name": "CPU Fan RPM - NCT6798", "label": "CPU Fan",
                "chip": "nct6798", "rpm": 1240,
            }
        },
        "guests": {
            "vms": {
                "110": {
                    "kind": "vm", "guest_id": "110", "name": "haos", "status": "stopped",
                    "agent_enabled": True, "qemu_agent": "unavailable", "passthrough_count": 0,
                },
                "501": {
                    "kind": "vm", "guest_id": "501", "name": "plex-vm", "status": "running",
                    "agent_enabled": True, "qemu_agent": "available", "passthrough_count": 1,
                },
                "700": {
                    "kind": "vm", "guest_id": "700", "name": "TrueNAS", "status": "running",
                    "agent_enabled": True, "qemu_agent": "available", "passthrough_count": 1,
                },
            },
            "lxcs": {
                "500": {
                    "kind": "lxc", "guest_id": "500", "name": "recorder", "status": "running",
                    "agent_enabled": None, "qemu_agent": "not_applicable", "passthrough_count": 0,
                }
            },
            "summary": {
                "vms": {"total": 3, "running": 2, "paused": 0, "stopped": 1, "unknown": 0},
                "lxcs": {"total": 1, "running": 1, "paused": 0, "stopped": 0, "unknown": 0},
            },
        },
        "topology": {
            "revision": "abc123",
            "assignments": {
                "pci_0000_00_17_0": {
                    "connection": "passthrough_pci",
                    "owner_kind": "vm",
                    "owner_id": "700",
                    "owner_name": "TrueNAS",
                    "config_key": "hostpci0",
                    "pci_address": "0000:00:17.0",
                    "pci_class": "0106",
                    "class_name": "SATA controller",
                    "model": "Intel Corporation Device",
                },
                "pci_0000_00_02_0": {
                    "connection": "passthrough_pci",
                    "owner_kind": "vm",
                    "owner_id": "501",
                    "owner_name": "plex-vm",
                    "config_key": "hostpci0",
                    "pci_address": "0000:00:02.0",
                    "pci_class": "0300",
                    "class_name": "VGA compatible controller",
                    "model": "Intel Alder Lake-N UHD Graphics",
                },
            },
        },
    }


def test_static_monitoring_entities_are_present():
    c = build_full_discovery_payload(_config(), _identity(), version="0.1.0")["components"]
    assert c["system"]["default_entity_id"] == "sensor.dh_pve_system"
    assert c["last_boot"]["default_entity_id"] == "sensor.dh_pve_last_boot"
    assert c["cpu_usage"]["default_entity_id"] == "sensor.dh_pve_cpu_usage"
    assert c["cpu_throttling"]["default_entity_id"] == "binary_sensor.dh_pve_cpu_throttling"
    assert c["memory_usage"]["default_entity_id"] == "sensor.dh_pve_memory_usage"
    assert c["collector_smart"]["default_entity_id"] == "binary_sensor.dh_pve_smart_collector"


def test_dynamic_storage_uses_used_total_semantics_and_attrs():
    c = build_full_discovery_payload(_config(), _identity(), version="0.1.0", inventory=_inventory())["components"]
    s = c["storage_local_lvm_usage"]
    assert s["default_entity_id"] == "sensor.dh_pve_storage_local_lvm_usage"
    assert "usage_percent" in s["value_template"]
    assert "used_gib" in s["json_attributes_template"]
    assert "total_gib" in s["json_attributes_template"]
    assert "available_gib" not in s["json_attributes_template"]
    assert "proxmox_integration" in s["json_attributes_template"]


def test_nvme_entities_are_compact_and_history_friendly():
    c = build_full_discovery_payload(_config(), _identity(), version="0.1.0", inventory=_inventory())["components"]
    prefix = "disk_wwn_eui_0025382451a05c68"
    assert c[prefix + "_temperature"]["unit_of_measurement"] == "°C"
    assert c[prefix + "_wear"]["unit_of_measurement"] == "%"
    assert c[prefix + "_daily_max_temperature"]["device_class"] == "temperature"
    assert c[prefix + "_unsafe_shutdowns"]["state_class"] == "total_increasing"
    assert "recommendation" in c[prefix + "_health"]["json_attributes_template"]
    assert len(c[prefix + "_health"]["availability"]) == 3


def test_dynamic_gpu_and_fan_entities_are_stable():
    c = build_full_discovery_payload(_config(), _identity(), version="0.1.0", inventory=_inventory())["components"]
    assert c["gpu_pci_0000_00_02_0_owner"]["default_entity_id"] == "sensor.dh_pve_gpu_pci_0000_00_02_0_owner"
    assert c["gpu_pci_0000_00_02_0_transcoding"]["unit_of_measurement"] == "%"
    assert c["fan_nct6798_isa_0290_fan1_rpm"]["unit_of_measurement"] == "rpm"


def test_subsystem_entities_use_two_level_availability():
    c = build_full_discovery_payload(_config(), _identity(), version="0.1.0", inventory=_inventory())["components"]
    cpu = c["cpu_usage"]
    assert len(cpu["availability"]) == 2
    assert cpu["availability_mode"] == "all"
    assert "subsystems.cpu.available" in cpu["availability"][1]["value_template"]


def test_guest_discovery_exposes_read_only_vm_lxc_and_summaries():
    c = build_guest_aware_discovery_payload(
        _config(), _identity(), version="0.1.0", inventory=_inventory()
    )["components"]
    vm = c["vm_700_status"]
    assert vm["default_entity_id"] == "sensor.dh_pve_vm_700_status"
    assert "subsystems.guests.data.vms" in vm["value_template"]
    assert "['700']" in vm["value_template"] or '["700"]' in vm["value_template"]
    assert '"guest_id"' in vm["json_attributes_template"]
    assert '"qemu_agent"' in vm["json_attributes_template"]
    assert c["lxc_500_status"]["default_entity_id"] == "sensor.dh_pve_lxc_500_status"
    assert c["vms_summary"]["default_entity_id"] == "sensor.dh_pve_vms"
    assert c["lxcs_summary"]["default_entity_id"] == "sensor.dh_pve_lxcs"
    guest_components = [item for key, item in c.items() if key.startswith(("vm_", "lxc_", "vms_", "lxcs_"))]
    assert all("command_topic" not in item for item in guest_components)


def test_passthrough_discovery_exposes_owner_and_pci_metadata_read_only():
    c = build_guest_aware_discovery_payload(
        _config(), _identity(), version="0.1.0", inventory=_inventory()
    )["components"]
    item = c["passthrough_pci_0000_00_17_0"]
    assert item["default_entity_id"] == "sensor.dh_pve_passthrough_pci_0000_00_17_0"
    assert "VM 700" in item["value_template"]
    attrs = item["json_attributes_template"]
    for key in ("pci_address", "pci_class", "class_name", "model", "config_key", "owner_id", "owner_name"):
        assert key in attrs
    assert "command_topic" not in item
