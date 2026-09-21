from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from .collectors.cooling import FanSnapshot


class BeelinkIt8613FanAdapter:
    profile_name = "beelink_it8613_v1"

    def __init__(
        self,
        *,
        dmi_root: Path = Path("/sys/class/dmi/id"),
    ) -> None:
        self.dmi_root = dmi_root

    @staticmethod
    def _read(path: Path) -> str:
        return path.read_text(encoding="utf-8").strip()

    @staticmethod
    def _write(path: Path, value: str) -> None:
        path.write_text(f"{value}\n", encoding="utf-8")

    def _dmi_values(self) -> tuple[str, ...]:
        values = []
        for name in ("sys_vendor", "product_name", "board_vendor", "board_name"):
            try:
                values.append(self._read(self.dmi_root / name))
            except OSError:
                values.append("")
        return tuple(values)

    def _dmi_supported(self) -> bool:
        combined = " ".join(self._dmi_values()).casefold()
        return "beelink" in combined or "azw" in combined

    @staticmethod
    def _paths(fan: FanSnapshot) -> tuple[Path, Path, Path]:
        input_path = Path(fan.input_path)
        root = input_path.parent
        index = fan.fan_index
        return (
            input_path,
            root / f"pwm{index}",
            root / f"pwm{index}_enable",
        )

    def supports(self, fan: FanSnapshot) -> bool:
        if not self._dmi_supported():
            return False
        if not (
            fan.chip == "it8613"
            and fan.source_device == "it87.2608"
            and fan.fan_index == 2
        ):
            return False
        input_path, pwm_path, enable_path = self._paths(fan)
        return (
            input_path.is_file()
            and pwm_path.is_file()
            and enable_path.is_file()
        )

    def hardware_identity(self, fan: FanSnapshot) -> str:
        material = "|".join(
            (
                self.profile_name,
                *self._dmi_values(),
                fan.chip,
                fan.source_device,
                fan.fan_name,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def capture(self, fan: FanSnapshot) -> Mapping[str, str]:
        _input, pwm_path, enable_path = self._paths(fan)
        return {
            "pwm": self._read(pwm_path),
            "pwm_enable": self._read(enable_path),
        }

    def enter_max(self, fan: FanSnapshot) -> None:
        _input, pwm_path, enable_path = self._paths(fan)
        self._write(enable_path, "1")
        self._write(pwm_path, "255")
        if self._read(pwm_path) != "255":
            raise RuntimeError("maximum PWM command did not verify")

    def read_rpm(self, fan: FanSnapshot) -> int | None:
        input_path, _pwm_path, _enable_path = self._paths(fan)
        raw = self._read(input_path)
        return int(raw) if raw.isdigit() else None

    def restore(self, fan: FanSnapshot, original: Mapping[str, str]) -> None:
        _input, pwm_path, enable_path = self._paths(fan)
        self._write(pwm_path, str(original["pwm"]))
        self._write(enable_path, str(original["pwm_enable"]))

    def verify_restored(
        self, fan: FanSnapshot, original: Mapping[str, str]
    ) -> bool:
        _input, pwm_path, enable_path = self._paths(fan)
        return (
            self._read(pwm_path) == str(original["pwm"])
            and self._read(enable_path) == str(original["pwm_enable"])
        )

    def original_is_max(self, original: Mapping[str, str]) -> bool:
        try:
            return int(str(original.get("pwm", "0"))) >= 250
        except ValueError:
            return False
