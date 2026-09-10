from pathlib import Path

from app.config import AppConfig, GeneralConfig, MqttConfig
from app.discovery import build_discovery_payload
from app.discovery_metrics import build_full_discovery_payload
from app.identity import HostIdentity
from app.production import ProductionCollectors
from app.state_store import StateStore


def _config() -> AppConfig:
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


def _identity() -> HostIdentity:
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="0123456789abcdef0123456789abcdef",
        hostname="pve",
        node_name="PVE",
    )


def test_controls_and_runtime_settings_have_semantic_metadata():
    components = build_discovery_payload(
        _config(), _identity(), version="0.1.0"
    )["components"]

    for key in ("refresh", "last_refresh", "setting_cpu_publish_delta"):
        component = components[key]
        assert component["json_attributes_topic"]
        template = component["json_attributes_template"]
        assert "proxmox_integration" in template
        assert "proxmox_section" in template
        assert "proxmox_subject" in template
        assert "proxmox_metric" in template
        assert "proxmox_object_id" in template
        assert "proxmox_display_name" in template
        assert "proxmox_sort_key" in template


def test_collector_names_preserve_known_acronyms():
    components = build_full_discovery_payload(
        _config(), _identity(), version="0.1.0"
    )["components"]

    assert components["collector_cpu"]["name"] == "CPU collector"
    assert components["collector_gpu"]["name"] == "GPU collector"
    assert components["collector_smart"]["name"] == "SMART collector"
    assert components["collector_host"]["name"] == "Host collector"


def test_python_fan_collector_emits_normalized_summary_when_no_fan_exists(tmp_path: Path):
    collectors = ProductionCollectors(
        node_name="PVE",
        disk_state_store=StateStore(tmp_path / "disks.json"),
        sys_root=tmp_path / "sys",
        proc_root=tmp_path / "proc",
        pve_root=tmp_path / "pve",
    )

    sample = collectors.fans()

    assert sample.data == {
        "detected": False,
        "count": 0,
        "status": "Not detected",
        "items": {},
    }
    assert sample.metrics["detected"].value is False
    assert sample.metrics["count"].value == 0


def test_python_fan_collector_emits_items_and_detected_summary(tmp_path: Path):
    hwmon = tmp_path / "sys" / "class" / "hwmon" / "hwmon4"
    hwmon.mkdir(parents=True)
    (hwmon / "name").write_text("nct6798\n", encoding="utf-8")
    (hwmon / "fan1_input").write_text("1240\n", encoding="utf-8")
    (hwmon / "fan1_label").write_text("CPU Fan\n", encoding="utf-8")

    collectors = ProductionCollectors(
        node_name="PVE",
        disk_state_store=StateStore(tmp_path / "disks.json"),
        sys_root=tmp_path / "sys",
        proc_root=tmp_path / "proc",
        pve_root=tmp_path / "pve",
    )
    sample = collectors.fans()

    assert sample.data["detected"] is True
    assert sample.data["count"] == 1
    assert sample.data["status"] == "Detected"
    assert len(sample.data["items"]) == 1
    fan = next(iter(sample.data["items"].values()))
    assert fan["rpm"] == 1240
    assert sample.metrics["detected"].value is True
    assert sample.metrics["count"].value == 1


def test_full_discovery_exposes_fan_status_without_template_counting():
    inventory = {
        "fans": {
            "detected": False,
            "count": 0,
            "status": "Not detected",
            "items": {},
        }
    }
    components = build_full_discovery_payload(
        _config(), _identity(), version="0.1.0", inventory=inventory
    )["components"]

    fan_status = components["fans_status"]
    assert fan_status["default_entity_id"] == "sensor.dh_pve_fans"
    assert ".status" in fan_status["value_template"]
    assert "| count" not in fan_status["value_template"]
    assert "count" in fan_status["json_attributes_template"]
    assert fan_status["entity_category"] == "diagnostic"
