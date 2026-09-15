from __future__ import annotations

import json
import math
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path


Runner = Callable[..., str]


@dataclass(frozen=True)
class DiskTemperatureSample:
    device_path: str
    temperature_c: float | None
    source: str


def _default_runner(argv: list[str], *, timeout: float = 20.0, check: bool = True) -> str:
    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )
    return completed.stdout


def _temperature(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not math.isfinite(result):
        return None
    if result < -50.0 or result > 200.0:
        return None
    return result


def _smart_temperature(payload: object) -> float | None:
    if not isinstance(payload, Mapping):
        return None

    temperature = payload.get("temperature")
    if isinstance(temperature, Mapping):
        current = _temperature(temperature.get("current"))
        if current is not None:
            return current

    nvme = payload.get("nvme_smart_health_information_log")
    if isinstance(nvme, Mapping):
        current = _temperature(nvme.get("temperature"))
        if current is not None:
            return current

    ata = payload.get("ata_smart_attributes")
    table = ata.get("table") if isinstance(ata, Mapping) else None
    if isinstance(table, list):
        values: list[float] = []
        for item in table:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name") or "").casefold()
            if "temperature" not in name:
                continue
            raw = item.get("raw")
            if isinstance(raw, Mapping):
                current = _temperature(raw.get("value"))
                if current is not None:
                    values.append(current)
        if values:
            return max(values)

    return None


class DiskTemperatureReader:
    def __init__(
        self,
        *,
        sys_root: Path = Path("/sys"),
        runner: Runner = _default_runner,
    ) -> None:
        self.sys_root = sys_root
        self.runner = runner

    def _sysfs_temperature(self, device_path: str) -> float | None:
        name = Path(device_path).name
        candidates = list(
            (self.sys_root / "class" / "block" / name / "device" / "hwmon").glob(
                "hwmon*/temp*_input"
            )
        )

        if name.startswith("nvme") and "n" in name:
            controller = name.split("n", 1)[0]
            candidates.extend(
                (self.sys_root / "class" / "nvme" / controller / "device" / "hwmon").glob(
                    "hwmon*/temp*_input"
                )
            )

        values: list[float] = []
        for path in candidates:
            try:
                raw = path.read_text(encoding="utf-8").strip()
                value = float(raw) / 1000.0
            except (OSError, ValueError):
                continue
            current = _temperature(value)
            if current is not None:
                values.append(current)
        return max(values) if values else None

    def _smartctl_temperature(self, device_path: str) -> float | None:
        try:
            raw = self.runner(
                ["smartctl", "-A", "-j", "-n", "standby", device_path],
                timeout=8.0,
                check=False,
            )
            payload = json.loads(raw)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, TypeError, ValueError):
            return None
        return _smart_temperature(payload)

    def read(self, device_path: str) -> DiskTemperatureSample:
        sysfs = self._sysfs_temperature(device_path)
        if sysfs is not None:
            return DiskTemperatureSample(
                device_path=device_path,
                temperature_c=sysfs,
                source="sysfs",
            )

        smart = self._smartctl_temperature(device_path)
        if smart is not None:
            return DiskTemperatureSample(
                device_path=device_path,
                temperature_c=smart,
                source="smartctl",
            )

        return DiskTemperatureSample(
            device_path=device_path,
            temperature_c=None,
            source="unavailable",
        )
