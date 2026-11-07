"""Strict read-only AST2500 passive maximum RPM calibration tests."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from subprocess import CompletedProcess

from app.collectors.cooling import parse_ipmi_fan_sdr
from app.fan_calibration import FanCalibrationManager, FanCalibrationRegistry
from app.fan_hardware_ipmi_passive import AsrockAst2500PassiveFanAdapter
from app.state_store import StateStore


BMC_INFO = """
Device ID                 : 32
Firmware Revision         : 1.20
Manufacturer ID           : 49622
Product ID                : 514 (0x0202)
"""
FANS = parse_ipmi_fan_sdr(
    "FAN1 | 60h | ok | 7.0 | 1700 RPM\n"
    "FAN3 | 62h | ok | 7.0 | 700 RPM\n"
)


class FakeReadOnlyBmc:
    def __init__(self):
        self.duty = [40, 40, 80, 60, 60, 40, 60, 60, 0, 0, 0, 0, 0, 0, 0, 0]
        self.info = BMC_INFO
        self.calls = []
        self.fan_rpm = {"FAN1": 1700, "FAN3": 700}

    def run(self, args, **kwargs):
        self.calls.append(tuple(args))
        assert args[:3] == ["ipmitool", "-I", "open"]
        assert kwargs == {"check": True, "capture_output": True, "text": True, "timeout": 6}
        assert args[3:] in (["mc", "info"], ["raw", "0x3a", "0xda"]), (
            "no other raw IPMI command, especially writes, is permitted"
        )
        if args[3:] == ["mc", "info"]:
            output = self.info
        else:
            output = " ".join(f"{x:02x}" for x in self.duty)
        return CompletedProcess(args, 0, output, "")

    def fans(self):
        return tuple(replace(fan, rpm=self.fan_rpm[fan.label]) for fan in FANS)


def _adapter(tmp_path: Path, bmc: FakeReadOnlyBmc):
    board = tmp_path / "board_name"
    machine = tmp_path / "machine-id"
    board.write_text("X570D4U-2L2T\n")
    machine.write_text("test-machine\n")
    return AsrockAst2500PassiveFanAdapter(
        board_name_path=board,
        machine_id_path=machine,
        runner=bmc.run,
        fan_reader=bmc.fans,
    )


def test_asrock_bmc_120_duty_readback_is_valid_but_does_not_allow_writes(tmp_path):
    bmc = FakeReadOnlyBmc()
    adapter = _adapter(tmp_path, bmc)
    assert adapter.supports(FANS[0])
    assert adapter.supports(FANS[1])
    assert adapter.ready_to_calibrate(FANS[0]) is False
    assert adapter.ready_to_calibrate(FANS[1]) is False
    try:
        adapter.enter_max(FANS[0])
    except RuntimeError as exc:
        assert "BMC duty changed" in str(exc)
    else:
        assert False, "must reject active max when not already naturally at 100%"
    assert all(call[3:] in (("mc", "info"), ("raw", "0x3a", "0xda")) for call in bmc.calls)


def test_passive_fan_calibration_collects_verified_natural_max_without_ipmi_writes(tmp_path):
    bmc = FakeReadOnlyBmc()
    adapter = _adapter(tmp_path, bmc)
    registry = FanCalibrationRegistry(StateStore(tmp_path / "calibration.json"))
    fan = FANS[0]
    assert registry.needs_automatic_calibration(fan, adapter) is False
    before = registry.presentation(fan, adapter)
    assert before["calibration_status"] == "waiting_for_full_pwm"
    assert before["speed_percent"] is None
    assert before["calibration_read_only"] is True

    # BMC independently reaches 100%: agent is allowed to *observe* RPM.
    bmc.duty[0] = 100
    assert adapter.ready_to_calibrate(fan)
    assert registry.needs_automatic_calibration(fan, adapter) is True
    manager = FanCalibrationManager(
        registry=registry,
        adapters=(adapter,),
        now_iso=lambda: "2026-11-08T03:00:00+05:00",
        sleep=lambda _: None,
    )
    result = manager.calibrate((fan,), automatic=True)
    assert result[fan.fan_id] == "calibrated"
    status = registry.presentation(fan, adapter)
    assert status["max_rpm"] == 1700
    assert status["speed_percent"] == 100
    assert status["max_rpm_source"] == "passive_full_duty"
    assert status["calibration_read_only"] is True

    bmc.duty[0] = 40
    bmc.fan_rpm["FAN1"] = 850
    # Previously saved true full-speed plateau remains the denominator.
    assert registry.presentation(bmc.fans()[0], adapter)["speed_percent"] == 50
    assert registry.needs_automatic_calibration(bmc.fans()[0], adapter) is False
    assert all(call[3:] in (("mc", "info"), ("raw", "0x3a", "0xda")) for call in bmc.calls)


def test_bmc_fails_closed_on_bad_board_firmware_invalid_duty_or_fan_label(tmp_path):
    bmc = FakeReadOnlyBmc()
    adapter = _adapter(tmp_path, bmc)
    other_fan = replace(FANS[0], label="SYS_FAN1")
    assert not adapter.supports(other_fan)
    bmc.duty[0] = 120
    assert not adapter.supports(FANS[0])
    bmc.duty[0] = 40
    board = tmp_path / "board_name"
    board.write_text("Other ASRock\n")
    # A new adapter must establish independent board identity.
    assert AsrockAst2500PassiveFanAdapter(
        board_name_path=board,
        runner=bmc.run,
    ).supports(FANS[0]) is False

    bmc.info = BMC_INFO.replace("1.20", "1.35")
    fw_adapter = _adapter(tmp_path, bmc)
    assert fw_adapter.supports(FANS[0]) is False


def test_bmc_rejects_mid_measurement_duty_drop_without_restore_or_writes(tmp_path):
    bmc = FakeReadOnlyBmc()
    adapter = _adapter(tmp_path, bmc)
    bmc.duty[2] = 100
    fan = FANS[1]
    assert adapter.capture(fan) == {"method": "passive", "duty": "100"}
    bmc.duty[2] = 60
    assert adapter.read_rpm(fan) is None
    adapter.restore(fan, {"method": "passive", "duty": "100"})
    assert adapter.verify_restored(fan, {"method": "passive", "duty": "100"})
    assert all(call[3:] in (("mc", "info"), ("raw", "0x3a", "0xda")) for call in bmc.calls)
