from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FanSnapshot:
    fan_id: str
    chip: str
    chip_display_name: str
    source_device: str
    fan_name: str
    fan_index: int
    label: str
    display_name: str
    rpm: int | None
    available: bool
    input_path: str


def _sanitize(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return re.sub(r"_+", "_", value)


def _chip_display(chip: str) -> str:
    if re.fullmatch(r"nct[0-9]+", chip):
        return chip.upper()
    if chip == "nouveau":
        return "Nouveau GPU"
    return chip


def collect_fans(hwmon_root: Path = Path("/sys/class/hwmon")) -> tuple[FanSnapshot, ...]:
    if not hwmon_root.exists():
        return ()
    result: list[FanSnapshot] = []
    for hwmon in sorted(hwmon_root.glob("hwmon*")):
        if not hwmon.is_dir():
            continue
        try:
            chip = (hwmon / "name").read_text(encoding="utf-8").strip() or "hwmon"
        except OSError:
            chip = "hwmon"
        chip_display = _chip_display(chip)
        try:
            real = hwmon.resolve()
        except OSError:
            real = hwmon
        source_device = real.name or chip
        device_link = hwmon / "device"
        if device_link.exists():
            try:
                source_device = device_link.resolve().name or source_device
            except OSError:
                pass

        for input_path in sorted(hwmon.glob("fan*_input")):
            match = re.fullmatch(r"fan(?P<index>[0-9]+)_input", input_path.name)
            if not match:
                continue
            index = int(match.group("index"))
            fan_name = f"fan{index}"
            try:
                raw_label = (hwmon / f"{fan_name}_label").read_text(encoding="utf-8").strip()
            except OSError:
                raw_label = ""
            label = raw_label if raw_label and raw_label != fan_name else f"Fan {index}"
            display_name = f"{label} RPM - {chip_display}"
            try:
                raw = input_path.read_text(encoding="utf-8").strip()
                rpm = int(raw) if re.fullmatch(r"[0-9]+", raw) else None
            except (OSError, ValueError):
                rpm = None
            fan_id = _sanitize(f"{chip}_{source_device}_{fan_name}")
            result.append(
                FanSnapshot(
                    fan_id=fan_id,
                    chip=chip,
                    chip_display_name=chip_display,
                    source_device=source_device,
                    fan_name=fan_name,
                    fan_index=index,
                    label=label,
                    display_name=display_name,
                    rpm=rpm,
                    available=rpm is not None,
                    input_path=str(input_path),
                )
            )
    return tuple(result)
