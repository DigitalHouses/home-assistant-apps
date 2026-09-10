from __future__ import annotations

import json
from pathlib import Path

from app.collectors.cpu import (
    CpuTimes,
    cpu_usage_percent,
    parse_lscpu,
    read_cpu_frequency,
    read_cpu_temperature,
    read_throttle_counters,
    thermal_throttling_active,
)
from app.collectors.host import build_hardware_identity, parse_pve_manager_version
from app.collectors.memory import parse_meminfo
from app.models import ThrottleCounters


FIXTURES = Path(__file__).parent / "fixtures" / "host"


def test_dmi_prefers_real_system_identity():
    cases = json.loads((FIXTURES / "dmi_cases.json").read_text())
    hw = build_hardware_identity(cases["shahristan"])
    assert hw.manufacturer == "AZW"
    assert hw.model == "MINI S"
    assert hw.product_version is None
    assert hw.hardware_source == "system"


def test_dmi_falls_back_to_board_for_oem_placeholders():
    cases = json.loads((FIXTURES / "dmi_cases.json").read_text())
    hw = build_hardware_identity(cases["legacy_i3"])
    assert hw.manufacturer == "ASRock"
    assert hw.model == "H110M-DVS R3.0"
    assert hw.hardware_source == "board_fallback"


def test_parse_pve_manager_version():
    text = "proxmox-ve: 8.4.0\npve-manager: 8.4.19 (running version: 8.4.19/a68fb383814bb1e6)\n"
    assert parse_pve_manager_version(text) == "8.4.19"


def test_parse_meminfo_shahristan_values():
    snap = parse_meminfo((FIXTURES / "shahristan_meminfo.txt").read_text())
    assert snap.total_kib == 16152608
    assert snap.used_kib == 12021708
    assert snap.usage_percent == 74.4
    assert snap.swap_used_kib == 375040
    assert snap.swap_usage_percent == 1.5


def test_parse_lscpu_supports_both_real_topologies():
    n100 = parse_lscpu((FIXTURES / "shahristan_lscpu.txt").read_text())
    i3 = parse_lscpu((FIXTURES / "legacy_i3_lscpu.txt").read_text())
    assert (n100.cores, n100.threads, n100.model, n100.max_mhz) == (
        4, 4, "Intel(R) N100", 3400.0
    )
    assert (i3.cores, i3.threads, i3.model, i3.max_mhz) == (
        2, 4, "Intel(R) Core(TM) i3-7100 CPU @ 3.90GHz", 3900.0
    )


def test_cpu_usage_uses_delta_between_poll_samples():
    assert cpu_usage_percent(CpuTimes(1000, 700), CpuTimes(1200, 820)) == 40.0


def test_cpu_temperature_prefers_coretemp_package(tmp_path: Path):
    hwmon = tmp_path / "class" / "hwmon" / "hwmon2"
    hwmon.mkdir(parents=True)
    (hwmon / "name").write_text("coretemp\n")
    (hwmon / "temp1_label").write_text("Package id 0\n")
    (hwmon / "temp1_input").write_text("66000\n")
    zone = tmp_path / "class" / "thermal" / "thermal_zone1"
    zone.mkdir(parents=True)
    (zone / "type").write_text("x86_pkg_temp\n")
    (zone / "temp").write_text("65000\n")
    assert read_cpu_temperature(tmp_path) == 66.0


def test_cpu_temperature_falls_back_to_x86_pkg_temp(tmp_path: Path):
    zone = tmp_path / "class" / "thermal" / "thermal_zone1"
    zone.mkdir(parents=True)
    (zone / "type").write_text("x86_pkg_temp\n")
    (zone / "temp").write_text("65000\n")
    assert read_cpu_temperature(tmp_path) == 65.0


def test_cpu_frequency_aggregates_policy_dirs(tmp_path: Path):
    base = tmp_path / "devices" / "system" / "cpu" / "cpufreq"
    for idx, cur in [(0, 2900063), (1, 2899925), (2, 2900105), (3, 2900453)]:
        policy = base / f"policy{idx}"
        policy.mkdir(parents=True)
        for name, value in {
            "scaling_cur_freq": cur,
            "cpuinfo_min_freq": 700000,
            "cpuinfo_max_freq": 3400000,
            "scaling_min_freq": 700000,
            "scaling_max_freq": 3400000,
        }.items():
            (policy / name).write_text(str(value) + "\n")
        (policy / "scaling_governor").write_text("performance\n")
    snap = read_cpu_frequency(tmp_path)
    assert snap.available is True
    assert snap.policy_count == 4
    assert snap.average_mhz == 2900.1
    assert snap.hardware_minimum_mhz == 700.0
    assert snap.hardware_maximum_mhz == 3400.0
    assert snap.scaling_governor == "performance"


def test_throttle_counters_use_package_max_across_cpus(tmp_path: Path):
    base = tmp_path / "devices" / "system" / "cpu"
    for idx, (count, total_ms) in enumerate(
        [(64925, 224646), (64925, 224787), (64925, 224717), (64925, 224700)]
    ):
        directory = base / f"cpu{idx}" / "thermal_throttle"
        directory.mkdir(parents=True)
        (directory / "package_throttle_count").write_text(str(count) + "\n")
        (directory / "package_throttle_total_time_ms").write_text(str(total_ms) + "\n")
        (directory / "core_throttle_count").write_text(str(count) + "\n")
        (directory / "core_throttle_total_time_ms").write_text(str(total_ms - 2) + "\n")
    snap = read_throttle_counters(tmp_path)
    assert snap.counter_source == "package"
    assert snap.count_since_boot == 64925
    assert snap.time_since_boot_ms == 224787
    assert snap.cpu_entry_count == 4


def test_thermal_throttling_requires_new_counter_and_100ms_delta():
    def snap(count: int, total_ms: int) -> ThrottleCounters:
        return ThrottleCounters(
            True, "package", count, total_ms, count, total_ms, count, total_ms, 4
        )

    previous = snap(64924, 224600)
    assert thermal_throttling_active(previous, snap(64925, 224787)) is True
    assert thermal_throttling_active(previous, snap(64925, 224650)) is False
    assert thermal_throttling_active(previous, previous) is False
