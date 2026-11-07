from __future__ import annotations

"""Capability-based driver for the standard Linux hwmon PWM sysfs ABI.

Only an input tachometer accompanied by its same-index PWM channel can be
considered. Mode 0 is read-only full-speed measurement. Modes 1 and 2
require an independently verified channel map, which is deliberately empty
in production; matching fanN/pwmN numbering alone is not sufficient.
Other vendor-defined automatic modes require a dedicated driver.
"""

import hashlib
import stat
from collections.abc import Mapping
from pathlib import Path

from .collectors.cooling import FanSnapshot


class HwmonPwmFanAdapter:
    profile_name = "hwmon_pwm_sysfs_v1"

    def __init__(
        self,
        *,
        machine_id_path: Path = Path("/etc/machine-id"),
        verified_active_channels: frozenset[str] = frozenset(),
    ) -> None:
        self.machine_id_path = machine_id_path
        # Never infer a fan/PWM electrical connection from matching numbers.
        # The runtime passes no verified channels until a trusted driver or
        # an independently validated capability probe establishes a mapping.
        self.verified_active_channels = frozenset(verified_active_channels)

    @staticmethod
    def _paths(fan: FanSnapshot) -> tuple[Path, Path, Path]:
        source = Path(fan.input_path)
        root = source.parent
        index = fan.fan_index
        return source, root / f"pwm{index}", root / f"pwm{index}_enable"

    @staticmethod
    def _read(path: Path) -> str:
        return path.read_text(encoding="ascii").strip()

    @staticmethod
    def _write(path: Path, value: str) -> None:
        path.write_text(f"{value}\n", encoding="ascii")

    @classmethod
    def _read_controls(cls, pwm: Path, enable: Path) -> dict[str, str]:
        duty = cls._read(pwm)
        mode = cls._read(enable)
        if not duty.isdecimal() or int(duty) > 255:
            raise ValueError("invalid hwmon PWM duty")
        if mode not in {"0", "1", "2"}:
            raise ValueError("unsupported hwmon PWM control mode")
        return {"pwm": duty, "pwm_enable": mode}

    def supports(self, fan: FanSnapshot) -> bool:
        if fan.chip == "ipmi" or fan.fan_index < 1:
            return False
        source, pwm, enable = self._paths(fan)
        if source.name != f"fan{fan.fan_index}_input":
            return False
        try:
            if not all(path.is_file() for path in (source, pwm, enable)):
                return False
            if not self._read(source).isdecimal():
                return False
            controls = self._read_controls(pwm, enable)
            # Mode 0 allows read-only full-speed measurement. Active PWM
            # control requires independent verification of channel wiring.
            if controls["pwm_enable"] != "0":
                if fan.fan_id not in self.verified_active_channels:
                    return False
                if not all(
                    path.stat().st_mode & stat.S_IWUSR for path in (pwm, enable)
                ):
                    return False
        except (OSError, ValueError, UnicodeError):
            return False
        return True

    def hardware_identity(self, fan: FanSnapshot) -> str:
        try:
            machine_id = self._read(self.machine_id_path)
        except (OSError, UnicodeError):
            machine_id = ""
        identity = "|".join(
            (self.profile_name, machine_id, fan.chip, fan.source_device, fan.fan_name)
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def capture(self, fan: FanSnapshot) -> Mapping[str, str]:
        if not self.supports(fan):
            raise RuntimeError("hwmon PWM controls are not safely accessible")
        _source, pwm, enable = self._paths(fan)
        return self._read_controls(pwm, enable)

    def enter_max(self, fan: FanSnapshot) -> None:
        # Guard the write boundary too: calibration manager capability checks
        # are not sufficient protection against a caller invoking us directly.
        if not self.supports(fan):
            raise RuntimeError("unverified fan/PWM mapping: refusing control")
        _source, pwm, enable = self._paths(fan)
        # Standard sysfs mode 0 already means full speed (no writes).
        if self._read(enable) == "0":
            return
        self._write(enable, "1")
        if self._read(enable) != "1":
            raise RuntimeError("hwmon PWM manual mode did not verify")
        self._write(pwm, "255")
        if self._read(pwm) != "255":
            raise RuntimeError("hwmon PWM maximum duty did not verify")

    def read_rpm(self, fan: FanSnapshot) -> int | None:
        source, _pwm, _enable = self._paths(fan)
        try:
            value = self._read(source)
        except (OSError, UnicodeError):
            return None
        return int(value) if value.isdecimal() else None

    def restore(self, fan: FanSnapshot, original: Mapping[str, str]) -> None:
        if original["pwm_enable"] == "0":
            # Read-only measurement: nothing was changed and nothing to undo.
            return
        _source, pwm, enable = self._paths(fan)
        # Restore duty before re-enabling the original automatic control.
        # A controller in auto mode may immediately compute its own PWM duty.
        self._write(pwm, str(original["pwm"]))
        self._write(enable, str(original["pwm_enable"]))

    def verify_restored(
        self, fan: FanSnapshot, original: Mapping[str, str]
    ) -> bool:
        _source, pwm, enable = self._paths(fan)
        try:
            if self._read(enable) != str(original["pwm_enable"]):
                return False
            if original["pwm_enable"] == "1":
                return self._read(pwm) == str(original["pwm"])
            # In automatic mode, the PWM output is allowed to change as
            # thermal control resumes; only the recovered mode is stable.
            return True
        except (OSError, UnicodeError, KeyError):
            return False

    @staticmethod
    def original_is_max(original: Mapping[str, str]) -> bool:
        if original.get("pwm_enable") == "0":
            return True
        try:
            return int(original.get("pwm", "0")) >= 250
        except ValueError:
            return False
