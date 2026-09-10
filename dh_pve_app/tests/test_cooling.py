from pathlib import Path

from app.collectors.cooling import collect_fans


def test_missing_hwmon_root_is_valid_no_fan_hardware(tmp_path: Path):
    assert collect_fans(tmp_path / "missing") == ()


def test_no_fan_inputs_is_valid_empty_inventory(tmp_path: Path):
    hw = tmp_path / "hwmon0"
    hw.mkdir()
    (hw / "name").write_text("coretemp\n")
    (hw / "temp1_input").write_text("65000\n")
    assert collect_fans(tmp_path) == ()


def test_zero_rpm_is_valid_measurement_and_label_fallback(tmp_path: Path):
    hw = tmp_path / "hwmon0"
    hw.mkdir()
    (hw / "name").write_text("nct6798\n")
    (hw / "fan1_input").write_text("0\n")
    fans = collect_fans(tmp_path)
    assert len(fans) == 1
    fan = fans[0]
    assert fan.rpm == 0
    assert fan.available is True
    assert fan.label == "Fan 1"
    assert fan.chip_display_name == "NCT6798"
    assert fan.fan_id.endswith("_fan1")


def test_labelled_fan_has_stable_identity_and_rpm(tmp_path: Path):
    hw = tmp_path / "hwmon4"
    hw.mkdir()
    (hw / "name").write_text("nct6798\n")
    (hw / "fan2_input").write_text("842\n")
    (hw / "fan2_label").write_text("CPU Fan\n")
    fan = collect_fans(tmp_path)[0]
    assert fan.rpm == 842
    assert fan.label == "CPU Fan"
    assert fan.display_name == "CPU Fan RPM - NCT6798"
    assert fan.fan_id == "nct6798_hwmon4_fan2"


def test_invalid_rpm_keeps_fan_present_but_unavailable(tmp_path: Path):
    hw = tmp_path / "hwmon1"
    hw.mkdir()
    (hw / "name").write_text("nouveau\n")
    (hw / "fan1_input").write_text("broken\n")
    fan = collect_fans(tmp_path)[0]
    assert fan.rpm is None
    assert fan.available is False
    assert fan.chip_display_name == "Nouveau GPU"


def test_fan_identity_uses_underlying_device_not_hwmon_number(tmp_path: Path):
    device = tmp_path / "devices" / "platform" / "nct6775.656"
    device.mkdir(parents=True)
    hw = tmp_path / "hwmon7"
    hw.mkdir()
    (hw / "name").write_text("nct6798\n")
    (hw / "fan1_input").write_text("1200\n")
    (hw / "device").symlink_to(device, target_is_directory=True)
    fan = collect_fans(tmp_path)[0]
    assert fan.source_device == "nct6775.656"
    assert fan.fan_id == "nct6798_nct6775_656_fan1"
