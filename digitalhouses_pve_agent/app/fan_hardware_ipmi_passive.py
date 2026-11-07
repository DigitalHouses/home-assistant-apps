from __future__ import annotations

"""Read-only full-PWM RPM measurement on verified ASRock Rack AST2500 BMC.

No fan-mode or duty writes. The BMC stays fully in control. The only
calibration opportunity is when the BMC *itself* sets a channel to 100%.
The independent mode getter is broken (0xcc) on X570D4U-2L2T BMC 1.20,
so any approach that temporarily forces 100% would be unsafe.
"""

import hashlib
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from .collectors.cooling import FanSnapshot, collect_ipmi_fans


class AsrockAst2500PassiveFanAdapter:
    profile_name = "asrock_ast2500_ipmi_passive_100_v1"
    # Never present this profile as a user-controllable calibration button.
    read_only_calibration = True

    def __init__(
        self,
        *,
        board_name_path: Path = Path("/sys/class/dmi/id/board_name"),
        machine_id_path: Path = Path("/etc/machine-id"),
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        fan_reader: Callable[[], tuple[FanSnapshot, ...]] = collect_ipmi_fans,
    ) -> None:
        self.board_name_path = board_name_path
        self.machine_id_path = machine_id_path
        self.runner = runner
        self.fan_reader = fan_reader
        self._identity_retry_after = 0.0
        self._bmc_identity: str | None = None

    def _run(self, *args: str) -> str | None:
        try:
            result = self.runner(
                ["ipmitool", "-I", "open", *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=6,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip()

    @staticmethod
    def _read(path: Path) -> str:
        return path.read_text(encoding="utf-8").strip()

    def _verified_bmc_identity(self) -> str | None:
        if self._bmc_identity is not None:
            return self._bmc_identity
        now = time.monotonic()
        if now < self._identity_retry_after:
            return None
        # A BMC can become available after the agent starts. Retry initial
        # negative identification without hammering its local IPMI interface.
        self._identity_retry_after = now + 60.0
        try:
            board = self._read(self.board_name_path)
        except OSError:
            return None
        # This precise protocol and channel map was observed on this board.
        if board != "X570D4U-2L2T":
            return None
        raw = self._run("mc", "info")
        if raw is None:
            return None
        fields: dict[str, str] = {}
        for line in raw.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()
        if (
            fields.get("Manufacturer ID") != "49622"
            or fields.get("Firmware Revision") != "1.20"
            or not fields.get("Product ID", "").startswith("514 ")
        ):
            return None
        self._bmc_identity = f"{board}|{fields['Manufacturer ID']}|{fields['Product ID']}|{fields['Firmware Revision']}"
        return self._bmc_identity

    def _duty(self, fan: FanSnapshot) -> int | None:
        if self._verified_bmc_identity() is None:
            return None
        if (
            fan.chip != "ipmi"
            or fan.source_device != "ipmi0"
            or fan.fan_index not in range(1, 7)
            or fan.label.upper() != f"FAN{fan.fan_index}"
        ):
            return None
        output = self._run("raw", "0x3a", "0xda")
        if output is None:
            return None
        tokens = output.split()
        # 16 fan-control bytes, in physical FANn header order.
        if len(tokens) != 16 or any(re.fullmatch(r"[0-9a-fA-F]{2}", token) is None for token in tokens):
            return None
        duty = [int(token, 16) for token in tokens]
        if any(value > 100 for value in duty):
            return None
        return duty[fan.fan_index - 1]

    def supports(self, fan: FanSnapshot) -> bool:
        # Hardware identification and duty readback alone, no mode assumptions.
        return self._duty(fan) is not None

    def ready_to_calibrate(self, fan: FanSnapshot) -> bool:
        # Only take a max-RPM sample if the BMC independently reports 100%.
        return self._duty(fan) == 100 and isinstance(fan.rpm, int) and fan.rpm > 0

    def hardware_identity(self, fan: FanSnapshot) -> str:
        try:
            machine = self._read(self.machine_id_path)
        except OSError:
            machine = ""
        parts = (
            self.profile_name,
            machine,
            self._verified_bmc_identity() or "unverified",
            fan.source_device,
            fan.label,
        )
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def capture(self, fan: FanSnapshot) -> Mapping[str, str]:
        if not self.ready_to_calibrate(fan):
            raise RuntimeError("BMC is not at verified 100% duty; refusing active calibration")
        return {"method": "passive", "duty": "100"}

    def enter_max(self, fan: FanSnapshot) -> None:
        # NO OPERATION ON HARDWARE. Assert the maximum is still natural.
        if not self.ready_to_calibrate(fan):
            raise RuntimeError("BMC duty changed; no maximum RPM measurement")

    def read_rpm(self, fan: FanSnapshot) -> int | None:
        if self._duty(fan) != 100:
            return None
        for sample in self.fan_reader():
            if sample.fan_id == fan.fan_id and sample.rpm is not None and sample.rpm > 0:
                return sample.rpm
        return None

    def restore(self, fan: FanSnapshot, original: Mapping[str, str]) -> None:
        # This adapter NEVER wrote to hardware. No state to restore.
        if original.get("method") != "passive":
            raise RuntimeError("invalid read-only calibration record")

    def verify_restored(self, fan: FanSnapshot, original: Mapping[str, str]) -> bool:
        return original.get("method") == "passive" and original.get("duty") == "100"

    @staticmethod
    def original_is_max(original: Mapping[str, str]) -> bool:
        return original.get("method") == "passive" and original.get("duty") == "100"
