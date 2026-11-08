"""Regression contract: one hardware-neutral PVE dashboard for AMD/Intel."""
from pathlib import Path
from app.collectors.cpu import read_cpu_temperature
from app.collectors.cooling import collect_fans, parse_ipmi_fan_sdr
from app.collectors.gpu import parse_lspci_gpus
from app.config import AppConfig, GeneralConfig, MqttConfig
from app.identity import HostIdentity
from app.shutdown_discovery import build_shutdown_aware_pve_discovery_payload


APP = Path(__file__).parents[1]


def _hwmon(root: Path, name: str, values: dict[str, str], index: int = 0):
    chip = root / "class" / "hwmon" / f"hwmon{index}"
    chip.mkdir(parents=True)
    (chip / "name").write_text(name + "\n")
    for key, value in values.items():
        (chip / key).write_text(str(value) + "\n")
    return chip


def test_amd_k10temp_tctl_fallback_preserves_single_cpu_entity(tmp_path):
    _hwmon(tmp_path, "nvme", {"temp1_input": "120000"}, index=0)
    _hwmon(tmp_path, "k10temp", {
        "temp1_label": "Tctl", "temp1_input": "39750",
        "temp3_label": "Tccd1", "temp3_input": "40250",
        "temp4_label": "Tccd2", "temp4_input": "41000",
    }, index=1)
    assert read_cpu_temperature(tmp_path) == 39.8


def test_amd_prefers_tdie_and_never_uses_ccd_as_package(tmp_path):
    chip = _hwmon(tmp_path, "k10temp", {
        "temp1_label": "Tctl", "temp1_input": "68000",
        "temp2_label": "Tdie", "temp2_input": "58000",
        "temp3_label": "Tccd1", "temp3_input": "83000",
    })
    assert read_cpu_temperature(tmp_path) == 58.0
    (chip / "temp2_input").write_text("broken\n")
    assert read_cpu_temperature(tmp_path) == 68.0
    (chip / "temp1_input").write_text("999999\n")
    assert read_cpu_temperature(tmp_path) is None


def test_amd_zenpower_supported_without_vendor_or_board_lookup(tmp_path):
    _hwmon(tmp_path, "zenpower", {
        "temp1_label": "Tdie", "temp1_input": "50250",
        "temp2_label": "Tctl", "temp2_input": "59430",
    })
    assert read_cpu_temperature(tmp_path) == 50.2


def test_intel_hottest_package_and_existing_thermal_fallback(tmp_path):
    _hwmon(tmp_path, "coretemp", {
        "temp1_label": "Package id 0", "temp1_input": "61000",
        "temp2_label": "Core 0", "temp2_input": "88000",
        "temp3_label": "Package id 1", "temp3_input": "63440",
    })
    assert read_cpu_temperature(tmp_path) == 63.4


def test_physical_gpu_inventory_ignores_service_and_virtual_vga():
    lspci = (
        "0000:29:00.0 VGA compatible controller [0300]: ASPEED Graphics Family "
        "[1a03:2000] (rev 41)\n"
        "    Kernel driver in use: ast\n"
        "0000:2f:00.0 VGA compatible controller [0300]: Intel DG2 Arc A310 "
        "[8086:56a6] (rev 05)\n"
        "    Kernel driver in use: vfio-pci\n"
        "0000:01:00.0 VGA compatible controller [0300]: Bochs VGA "
        "[1234:1111] (rev 02)\n"
        "    Kernel driver in use: bochs-drm\n"
    )
    gpus = parse_lspci_gpus(lspci)
    assert len(gpus) == 1
    assert gpus[0]["device_id"] == "0x56a6"
    assert gpus[0]["kernel_driver"] == "vfio-pci"


def test_hwmon_preserves_channel_number_without_enumeration(tmp_path):
    chip = tmp_path / "hwmon4"
    chip.mkdir()
    (chip / "name").write_text("nct6798\n")
    (chip / "fan3_input").write_text("1500\n")
    assert collect_fans(tmp_path)[0].label == "Fan 3"
    (chip / "fan3_label").write_text("SYS_FAN3\n")
    assert collect_fans(tmp_path)[0].label == "SYS_FAN3"


def test_gpu_hwmon_fan_does_not_prevent_bmc_chassis_reading(tmp_path):
    # Override the default root for a simulated /sys/class/hwmon.
    gpu = tmp_path / "hwmon0"
    gpu.mkdir()
    (gpu / "name").write_text("i915\n")
    (gpu / "fan1_input").write_text("3033\n")
    chassis = parse_ipmi_fan_sdr(
        "FAN1 | 60h | ok | 7.0 | 1700 RPM\n"
        "FAN3 | 62h | ok | 7.0 | 700 RPM\n"
    )
    from app.collectors.cooling import select_fan_sources
    gpu_fans = collect_fans(tmp_path)
    assert gpu_fans[0].label == "GPU Fan 1"
    selected = select_fan_sources(gpu_fans, chassis)
    assert [f.label for f in selected] == ["GPU Fan 1", "FAN1", "FAN3"]
    # A real board hwmon channel wins over IPMI, preventing duplicates.
    board = gpu_fans[0].__class__(
        **{**gpu_fans[0].__dict__, "chip": "nct6798", "label": "SYS_FAN1"}
    )
    selected = select_fan_sources((board,), chassis)
    assert [f.label for f in selected] == ["SYS_FAN1"]


def _discovery(inventory):
    config = AppConfig(
        general=GeneralConfig(instance_id="", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(
            host="mqtt", port=1883, username="", password="",
            topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
            discovery_prefix="homeassistant", keepalive_seconds=60,
        ),
    )
    identity = HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a", hostname="pve", node_name="PVE",
    )
    return build_shutdown_aware_pve_discovery_payload(
        config, identity, version="0.5.78", inventory=inventory
    )["components"]


def test_fan_discovery_uses_physical_label_from_hwmon_and_ipmi():
    components = _discovery({"fans": {
        "nct6798_board_fan3": {"label": "SYS_FAN3", "chip": "nct6798", "rpm": 900},
        "ipmi_ipmi0_fan1": {"label": "FAN1", "chip": "ipmi", "rpm": 1000},
    }})
    assert components["fan_nct6798_board_fan3_rpm"]["name"] == "SYS_FAN3 RPM"
    assert components["fan_ipmi_ipmi0_fan1_rpm"]["name"] == "FAN1 RPM"


def test_passive_bmc_fans_offer_percentage_but_no_active_calibration_button():
    components = _discovery({"fans": {
        "ipmi_ipmi0_fan1": {
            "label": "FAN1",
            "chip": "ipmi",
            "rpm": 1700,
            "calibration_supported": True,
            "calibration_read_only": True,
            "calibration_status": "waiting_for_full_pwm",
            "speed_percent": None,
        },
    }})
    assert "calibrate_fans" not in components
    assert "fan_ipmi_ipmi0_fan1_rpm" in components
    assert components["fan_ipmi_ipmi0_fan1_speed"]["unit_of_measurement"] == "%"
    assert "calibration_read_only" in (
        components["fan_ipmi_ipmi0_fan1_rpm"]["json_attributes_template"]
    )


def test_disk_capacity_is_published_on_existing_health_entity():
    components = _discovery({"smart": {"nvme_disk": {
        "model": "NVMe", "disk_type": "NVMe", "capacity_bytes": 1000204886016,
        "available": True, "health_state": "HEALTHY",
    }}})
    disk = components["disk_nvme_disk_health"]
    assert '"capacity_bytes":value_json.subsystems.smart.data.nvme_disk.capacity_bytes' in (
        disk["json_attributes_template"]
    )


def test_ups_buttons_present_and_dashboard_matches_sensor_capabilities():
    text = (APP / "examples/dh_pve_agent_dashboard_ru.yaml").read_text()
    for action in ("standard", "quick", "deep", "stop"):
        assert f"button.dh_pve_agent_ups_test_{action}" in text
        assert f"binary_sensor.dh_pve_agent_ups_{action}_test_supported" in text
    assert "sensor.dh_pve_agent_ups_test_result" in text
    assert "capacity_bytes" in text
    assert "GPU" in text
    assert "proxmox_metric') == 'rpm'" in text
    assert "Fan: Not detected" not in text
