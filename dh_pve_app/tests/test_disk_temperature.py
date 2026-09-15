from __future__ import annotations

from pathlib import Path

from app.disk_temperature import DiskTemperatureReader


def test_disk_temperature_uses_hwmon_without_smartctl(tmp_path: Path):
    sensor = tmp_path / "class" / "block" / "nvme0n1" / "device" / "hwmon" / "hwmon0"
    sensor.mkdir(parents=True)
    (sensor / "temp1_input").write_text("41000\n", encoding="utf-8")

    calls = []

    def runner(argv, *, timeout=20.0, check=True):
        calls.append(tuple(argv))
        raise AssertionError("smartctl must not run when hwmon is available")

    sample = DiskTemperatureReader(sys_root=tmp_path, runner=runner).read("/dev/nvme0n1")

    assert sample.temperature_c == 41.0
    assert sample.source == "sysfs"
    assert calls == []


def test_disk_temperature_falls_back_to_bounded_smart_read(tmp_path: Path):
    calls = []

    def runner(argv, *, timeout=20.0, check=True):
        calls.append(tuple(argv))
        return '{"temperature":{"current":37}}'

    sample = DiskTemperatureReader(sys_root=tmp_path, runner=runner).read("/dev/sda")

    assert sample.temperature_c == 37.0
    assert sample.source == "smartctl"
    assert len(calls) == 1
    argv = calls[0]
    assert argv[0] == "smartctl"
    assert "-A" in argv
    assert "-j" in argv
    assert "-n" in argv
    assert "standby" in argv
    assert "-a" not in argv


def test_invalid_hwmon_value_is_not_zero_and_uses_fallback(tmp_path: Path):
    sensor = tmp_path / "class" / "block" / "sda" / "device" / "hwmon" / "hwmon0"
    sensor.mkdir(parents=True)
    (sensor / "temp1_input").write_text("invalid\n", encoding="utf-8")

    def runner(argv, *, timeout=20.0, check=True):
        return '{"temperature":{"current":35}}'

    sample = DiskTemperatureReader(sys_root=tmp_path, runner=runner).read("/dev/sda")

    assert sample.temperature_c == 35.0
    assert sample.source == "smartctl"


def test_missing_temperature_returns_none_not_zero(tmp_path: Path):
    def runner(argv, *, timeout=20.0, check=True):
        return '{"smartctl":{"exit_status":0}}'

    sample = DiskTemperatureReader(sys_root=tmp_path, runner=runner).read("/dev/sda")

    assert sample.temperature_c is None
    assert sample.source == "unavailable"
