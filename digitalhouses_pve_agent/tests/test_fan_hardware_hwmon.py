from pathlib import Path
from unittest.mock import patch

from app.collectors.cooling import FanSnapshot
from app.fan_calibration import FanCalibrationManager, FanCalibrationRegistry
from app.fan_hardware_beelink import BeelinkIt8613FanAdapter
from app.fan_hardware_hwmon import HwmonPwmFanAdapter
from app.state_store import StateStore


def setup_hwmon(tmp_path: Path, *, mode="2", duty="95", index=1):
    chip = tmp_path / "hwmon" / "hwmon0"
    chip.mkdir(parents=True)
    (chip / f"fan{index}_input").write_text("1400\n")
    (chip / f"pwm{index}").write_text(duty + "\n")
    (chip / f"pwm{index}_enable").write_text(mode + "\n")
    machine = tmp_path / "machine-id"
    machine.write_text("machine-A\n")
    adapter = HwmonPwmFanAdapter(machine_id_path=machine)
    fan = FanSnapshot(
        fan_id=f"nct6798_isa_0290_fan{index}",
        chip="nct6798",
        chip_display_name="NCT6798",
        source_device="isa.0290",
        fan_name=f"fan{index}",
        fan_index=index,
        label=f"Fan {index}",
        display_name=f"Fan {index} - NCT6798",
        rpm=1400,
        available=True,
        input_path=str(chip / f"fan{index}_input"),
    )
    return adapter, fan, chip


def test_hwmon_pwm_capability_is_not_motherboard_specific(tmp_path):
    adapter, fan, chip = setup_hwmon(tmp_path)
    assert adapter.supports(fan)
    assert adapter.capture(fan) == {"pwm": "95", "pwm_enable": "2"}
    # No DMI / motherboard model is consulted.
    assert not (tmp_path / "dmi").exists()


def test_generic_pwm_max_restore_automatic_mode(tmp_path):
    adapter, fan, chip = setup_hwmon(tmp_path)
    saved = adapter.capture(fan)
    adapter.enter_max(fan)
    assert (chip / "pwm1").read_text().strip() == "255"
    assert (chip / "pwm1_enable").read_text().strip() == "1"
    adapter.restore(fan, saved)
    assert adapter.verify_restored(fan, saved)
    assert (chip / "pwm1_enable").read_text().strip() == "2"


def test_generic_pwm_max_restore_manual_mode(tmp_path):
    adapter, fan, chip = setup_hwmon(tmp_path, mode="1", duty="125")
    saved = adapter.capture(fan)
    adapter.enter_max(fan)
    adapter.restore(fan, saved)
    assert adapter.verify_restored(fan, saved)
    assert (chip / "pwm1").read_text().strip() == "125"
    assert (chip / "pwm1_enable").read_text().strip() == "1"


def test_automatic_pwm_output_may_change_after_restoring_auto_mode(tmp_path):
    adapter, fan, chip = setup_hwmon(tmp_path)
    saved = adapter.capture(fan)
    adapter.enter_max(fan)
    adapter.restore(fan, saved)
    # The PWM register reports the live duty, which automatic control changes.
    (chip / "pwm1").write_text("120\n")
    assert adapter.verify_restored(fan, saved)
    (chip / "pwm1_enable").write_text("1\n")
    assert not adapter.verify_restored(fan, saved)


def test_hwmon_probe_rejects_missing_mismatched_and_special_modes(tmp_path):
    adapter, fan, chip = setup_hwmon(tmp_path)
    (chip / "pwm1_enable").write_text("3\n")
    assert not adapter.supports(fan)
    (chip / "pwm1_enable").write_text("4\n")
    assert not adapter.supports(fan)
    (chip / "pwm1_enable").write_text("bad\n")
    assert not adapter.supports(fan)
    (chip / "pwm1_enable").write_text("2\n")
    (chip / "pwm1").write_text("900\n")
    assert not adapter.supports(fan)
    (chip / "pwm1").write_text("95\n")
    (chip / "pwm1").chmod(0o444)
    assert not adapter.supports(fan)
    (chip / "pwm1").chmod(0o644)
    (chip / "pwm1_enable").unlink()
    assert not adapter.supports(fan)


def test_hwmon_mode_zero_calibrates_at_full_speed_without_writes(tmp_path):
    adapter, fan, chip = setup_hwmon(tmp_path, mode="0", duty="0")
    # Linux sysfs ABI mode 0: fan speed control disabled => full speed.
    (chip / "pwm1").chmod(0o444)
    (chip / "pwm1_enable").chmod(0o444)
    assert adapter.supports(fan)
    registry = FanCalibrationRegistry(StateStore(tmp_path / "calibration.json"))
    manager = FanCalibrationManager(
        registry=registry, adapters=(adapter,),
        now_iso=lambda: "2026-11-07T20:00:00Z", sleep=lambda _: None,
    )
    with patch.object(adapter, "_write", side_effect=AssertionError("NO WRITES")):
        with patch.object(adapter, "read_rpm", side_effect=[1400, 1400, 1400, 1400]):
            result = manager.calibrate((fan,), automatic=True)
    assert result[fan.fan_id] == "calibrated"
    assert registry.record(fan, adapter)["max_rpm"] == 1400
    assert (chip / "pwm1_enable").read_text().strip() == "0"
    assert (chip / "pwm1").read_text().strip() == "0"


def test_hwmon_probe_never_touches_controls_on_ipmi_fans(tmp_path):
    adapter, fan, chip = setup_hwmon(tmp_path)
    ipmi = FanSnapshot(
        fan_id="ipmi_ipmi0_fan1", chip="ipmi",
        chip_display_name="BMC IPMI", source_device="ipmi0",
        fan_name="fan1", fan_index=1, label="FAN1",
        display_name="FAN1", rpm=1700, available=True,
        input_path="ipmi:sdr:FAN1",
    )
    assert not adapter.supports(ipmi)
    assert (chip / "pwm1").read_text().strip() == "95"
    assert (chip / "pwm1_enable").read_text().strip() == "2"


def test_hwmon_identity_is_hardware_scoped_not_runtime_index(tmp_path):
    adapter, fan, chip = setup_hwmon(tmp_path)
    first = adapter.hardware_identity(fan)
    # hwmonX numbering may change between boots.
    from dataclasses import replace
    renumbered = replace(fan, input_path=str(tmp_path / "hwmon" / "hwmon8" / "fan1_input"))
    assert adapter.hardware_identity(renumbered) == first
    (tmp_path / "machine-id").write_text("machine-B\n")
    assert adapter.hardware_identity(fan) != first


def test_hwmon_generic_calibration_saves_max_rpm_and_restores(tmp_path):
    adapter, fan, chip = setup_hwmon(tmp_path)
    registry = FanCalibrationRegistry(StateStore(tmp_path / "calibration.json"))
    manager = FanCalibrationManager(
        registry=registry,
        adapters=(BeelinkIt8613FanAdapter(dmi_root=tmp_path / "empty"), adapter),
        now_iso=lambda: "2026-11-07T20:00:00Z",
        sleep=lambda _: None,
    )
    assert manager.adapter_for(fan) is adapter
    # Baseline followed by a stabilized plateau after setting max duty.
    with patch.object(adapter, "read_rpm", side_effect=[1400, 1800, 1800, 1800]):
        result = manager.calibrate((fan,), automatic=True)
    assert result[fan.fan_id] == "calibrated"
    assert registry.record(fan, adapter)["max_rpm"] == 1800
    assert registry.presentation(fan, adapter)["speed_percent"] == 78
    assert (chip / "pwm1").read_text().strip() == "95"
    assert (chip / "pwm1_enable").read_text().strip() == "2"


def test_hwmon_failed_max_write_restores_original_mode(tmp_path):
    adapter, fan, chip = setup_hwmon(tmp_path)
    original_write = adapter._write

    def fails_max(path: Path, value: str) -> None:
        if value == "255":
            raise OSError("pwm write denied")
        original_write(path, value)

    registry = FanCalibrationRegistry(StateStore(tmp_path / "calibration.json"))
    manager = FanCalibrationManager(
        registry=registry, adapters=(adapter,),
        now_iso=lambda: "2026-11-07T20:00:00Z", sleep=lambda _: None,
    )
    with patch.object(adapter, "_write", side_effect=fails_max):
        result = manager.calibrate((fan,), automatic=True)
    assert result[fan.fan_id] == "failed"
    assert (chip / "pwm1_enable").read_text().strip() == "2"
    assert (chip / "pwm1").read_text().strip() == "95"


def test_hwmon_restore_failure_marked_and_pending_is_persisted(tmp_path):
    adapter, fan, chip = setup_hwmon(tmp_path)
    registry = FanCalibrationRegistry(StateStore(tmp_path / "calibration.json"))
    manager = FanCalibrationManager(
        registry=registry, adapters=(adapter,),
        now_iso=lambda: "2026-11-07T20:00:00Z", sleep=lambda _: None,
    )
    original_write = adapter._write

    def fails_restore(path: Path, value: str) -> None:
        if path.name.endswith("_enable") and value == "2":
            raise OSError("restore failed")
        original_write(path, value)

    with patch.object(adapter, "read_rpm", side_effect=[1400, 1800, 1800, 1800]):
        with patch.object(adapter, "_write", side_effect=fails_restore):
            result = manager.calibrate((fan,), automatic=True)
    assert result[fan.fan_id] == "restore_failed"
    assert registry.record(fan, adapter)["pending_restore"] == {
        "pwm": "95", "pwm_enable": "2"
    }
    # Simulated process recovery once the control path becomes available.
    assert manager.recover_pending((fan,))[fan.fan_id] == "recovered"
    assert (chip / "pwm1_enable").read_text().strip() == "2"


def test_existing_beelink_profile_precedes_generic_hwmon(tmp_path):
    # It8613 has an existing calibrated profile and must not be switched.
    dmi = tmp_path / "dmi"
    dmi.mkdir()
    (dmi / "sys_vendor").write_text("AZW\n")
    chip = tmp_path / "hwmon0"
    chip.mkdir()
    (chip / "fan2_input").write_text("3729\n")
    (chip / "pwm2").write_text("95\n")
    (chip / "pwm2_enable").write_text("2\n")
    fan = FanSnapshot(
        fan_id="it8613_it87_2608_fan2", chip="it8613", chip_display_name="it8613",
        source_device="it87.2608", fan_name="fan2", fan_index=2,
        label="Fan 2", display_name="Fan 2", rpm=3729, available=True,
        input_path=str(chip / "fan2_input"),
    )
    beelink = BeelinkIt8613FanAdapter(dmi_root=dmi)
    generic = HwmonPwmFanAdapter(machine_id_path=tmp_path / "machine-id")
    assert beelink.supports(fan)
    assert generic.supports(fan)
    registry = FanCalibrationRegistry(StateStore(tmp_path / "calibration.json"))
    manager = FanCalibrationManager(
        registry=registry, adapters=(beelink, generic),
        now_iso=lambda: "2026-11-07T20:00:00Z", sleep=lambda _: None,
    )
    assert manager.adapter_for(fan) is beelink
