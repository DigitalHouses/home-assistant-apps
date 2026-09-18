from pathlib import Path

from app.config import AppConfig, GeneralConfig, MqttConfig
from app.discovery import build_discovery_payload
from app.discovery_metrics import build_full_discovery_payload
from app.identity import HostIdentity
from app.production_v1 import ResilientProductionCollectors
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


def test_active_controls_have_semantic_metadata_and_poll_controls_are_absent():
    components = build_discovery_payload(
        _config(), _identity(), version="0.1.0"
    )["components"]

    for key in ("refresh", "last_refresh"):
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

    assert "setting_fast_poll_interval_seconds" not in components
    assert "setting_disk_poll_interval_seconds" not in components
    assert not any("publish_delta" in key for key in components)


def test_collector_names_preserve_known_acronyms():
    components = build_full_discovery_payload(
        _config(), _identity(), version="0.1.0"
    )["components"]

    assert components["collector_cpu"]["name"] == "CPU collector"
    assert components["collector_gpu"]["name"] == "GPU collector"
    assert components["collector_smart"]["name"] == "SMART collector"
    assert components["collector_host"]["name"] == "Host collector"


def _collectors(
    tmp_path: Path,
    *,
    fan_state_store: StateStore | None = None,
) -> ResilientProductionCollectors:
    kwargs = {}
    if fan_state_store is not None:
        kwargs["fan_state_store"] = fan_state_store
    return ResilientProductionCollectors(
        node_name="PVE",
        disk_state_store=StateStore(tmp_path / "disks.json"),
        sys_root=tmp_path / "sys",
        proc_root=tmp_path / "proc",
        pve_root=tmp_path / "pve",
        **kwargs,
    )


def _fan_items(sample) -> dict[str, dict[str, object]]:
    return {
        key: value
        for key, value in sample.data.items()
        if isinstance(value, dict)
    }


def _write_beelink_fans(tmp_path: Path, *, fan2: str, fan3: str = "0") -> Path:
    hwmon = tmp_path / "sys" / "class" / "hwmon" / "hwmon3"
    hwmon.mkdir(parents=True, exist_ok=True)
    (hwmon / "name").write_text("it8613\n", encoding="utf-8")
    device = tmp_path / "sys" / "devices" / "platform" / "it87.2608"
    device.mkdir(parents=True, exist_ok=True)
    device_link = hwmon / "device"
    if not device_link.exists():
        device_link.symlink_to(device, target_is_directory=True)
    (hwmon / "fan2_input").write_text(f"{fan2}\n", encoding="utf-8")
    (hwmon / "fan3_input").write_text(f"{fan3}\n", encoding="utf-8")
    return hwmon


def test_python_fan_collector_emits_normalized_summary_when_no_fan_exists(tmp_path: Path):
    sample = _collectors(tmp_path).fans()

    assert sample.data == {
        "detected": False,
        "count": 0,
        "candidate_count": 0,
        "confirmed_count": 0,
        "unconfirmed_count": 0,
        "candidate_ids": [],
        "status": "Not detected",
    }
    assert sample.metrics["detected"].value is False
    assert sample.metrics["count"].value == 0


def test_beelink_first_positive_sample_keeps_both_hwmon_channels_unconfirmed(tmp_path: Path):
    _write_beelink_fans(tmp_path, fan2="3792", fan3="0")
    collectors = _collectors(tmp_path)

    sample = collectors.fans()

    assert sample.data["detected"] is False
    assert sample.data["count"] == 0
    assert sample.data["candidate_count"] == 2
    assert sample.data["confirmed_count"] == 0
    assert sample.data["unconfirmed_count"] == 2
    assert sample.data["candidate_ids"] == [
        "it8613_it87_2608_fan2",
        "it8613_it87_2608_fan3",
    ]
    assert _fan_items(sample) == {}


def test_beelink_second_positive_sample_confirms_only_rotating_fan(tmp_path: Path):
    _write_beelink_fans(tmp_path, fan2="3792", fan3="0")
    collectors = _collectors(tmp_path)

    collectors.fans()
    sample = collectors.fans()

    assert sample.data["detected"] is True
    assert sample.data["count"] == 1
    assert sample.data["candidate_count"] == 2
    assert sample.data["confirmed_count"] == 1
    assert sample.data["unconfirmed_count"] == 1
    fans = _fan_items(sample)
    assert set(fans) == {"it8613_it87_2608_fan2"}
    assert fans["it8613_it87_2608_fan2"]["rpm"] == 3792


def test_confirmed_fan_remains_exposed_when_rpm_later_becomes_zero(tmp_path: Path):
    hwmon = _write_beelink_fans(tmp_path, fan2="3792", fan3="0")
    collectors = _collectors(tmp_path)

    collectors.fans()
    collectors.fans()
    (hwmon / "fan2_input").write_text("0\n", encoding="utf-8")

    sample = collectors.fans()

    assert sample.data["detected"] is True
    assert sample.data["count"] == 1
    assert sample.data["confirmed_count"] == 1
    fans = _fan_items(sample)
    assert set(fans) == {"it8613_it87_2608_fan2"}
    assert fans["it8613_it87_2608_fan2"]["rpm"] == 0


def test_zero_between_positive_samples_resets_fan_confirmation_debounce(tmp_path: Path):
    hwmon = _write_beelink_fans(tmp_path, fan2="3792", fan3="0")
    collectors = _collectors(tmp_path)

    assert collectors.fans().data["confirmed_count"] == 0

    (hwmon / "fan2_input").write_text("0\n", encoding="utf-8")
    assert collectors.fans().data["confirmed_count"] == 0

    (hwmon / "fan2_input").write_text("3813\n", encoding="utf-8")
    assert collectors.fans().data["confirmed_count"] == 0

    sample = collectors.fans()
    assert sample.data["confirmed_count"] == 1
    assert set(_fan_items(sample)) == {"it8613_it87_2608_fan2"}


def test_confirmed_fan_survives_collector_restart_with_persistent_store(tmp_path: Path):
    hwmon = _write_beelink_fans(tmp_path, fan2="3792", fan3="0")
    fan_store = StateStore(tmp_path / "fans.json")
    collectors = _collectors(tmp_path, fan_state_store=fan_store)

    collectors.fans()
    collectors.fans()
    (hwmon / "fan2_input").write_text("0\n", encoding="utf-8")

    restarted = _collectors(tmp_path, fan_state_store=fan_store)
    sample = restarted.fans()

    assert sample.data["detected"] is True
    assert sample.data["count"] == 1
    assert sample.data["candidate_count"] == 2
    assert sample.data["confirmed_count"] == 1
    assert sample.data["unconfirmed_count"] == 1
    fans = _fan_items(sample)
    assert set(fans) == {"it8613_it87_2608_fan2"}
    assert fans["it8613_it87_2608_fan2"]["rpm"] == 0


def test_full_discovery_exposes_fan_status_without_template_counting():
    inventory = {
        "fans": {
            "detected": False,
            "count": 0,
            "status": "Not detected",
        }
    }
    components = build_full_discovery_payload(
        _config(), _identity(), version="0.1.0", inventory=inventory
    )["components"]

    fan_status = components["fans_status"]
    assert fan_status["default_entity_id"] == "sensor.dh_app_pve_fans"
    assert ".status" in fan_status["value_template"]
    assert "| count" not in fan_status["value_template"]
    attrs = fan_status["json_attributes_template"]
    assert "count" in attrs
    assert "candidate_count" in attrs
    assert "confirmed_count" in attrs
    assert "unconfirmed_count" in attrs
    assert fan_status["entity_category"] == "diagnostic"
