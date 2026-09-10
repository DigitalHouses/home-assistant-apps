from __future__ import annotations

import math
from dataclasses import dataclass


class RuntimeSettingError(ValueError):
    pass


@dataclass(frozen=True)
class SettingSpec:
    key: str
    default: float
    minimum: float
    maximum: float
    step: float
    entity_id: str
    name: str
    unit: str | None = None


SETTING_SPECS: dict[str, SettingSpec] = {
    "fast_poll_interval_seconds": SettingSpec(
        key="fast_poll_interval_seconds",
        default=10.0,
        minimum=2.0,
        maximum=60.0,
        step=1.0,
        entity_id="number.dh_pve_fast_poll_interval",
        name="Fast poll interval",
        unit="s",
    ),
    "disk_poll_interval_seconds": SettingSpec(
        key="disk_poll_interval_seconds",
        default=30.0,
        minimum=10.0,
        maximum=300.0,
        step=5.0,
        entity_id="number.dh_pve_disk_poll_interval",
        name="Disk poll interval",
        unit="s",
    ),
    "cpu_publish_delta": SettingSpec(
        key="cpu_publish_delta",
        default=5.0,
        minimum=1.0,
        maximum=25.0,
        step=1.0,
        entity_id="number.dh_pve_cpu_publish_delta",
        name="CPU publish delta",
        unit="%",
    ),
    "memory_publish_delta": SettingSpec(
        key="memory_publish_delta",
        default=1.0,
        minimum=0.5,
        maximum=10.0,
        step=0.5,
        entity_id="number.dh_pve_memory_publish_delta",
        name="Memory publish delta",
        unit="%",
    ),
    "temperature_publish_delta": SettingSpec(
        key="temperature_publish_delta",
        default=1.0,
        minimum=0.5,
        maximum=10.0,
        step=0.5,
        entity_id="number.dh_pve_temperature_publish_delta",
        name="Temperature publish delta",
        unit="°C",
    ),
    "storage_publish_delta": SettingSpec(
        key="storage_publish_delta",
        default=0.5,
        minimum=0.1,
        maximum=5.0,
        step=0.1,
        entity_id="number.dh_pve_storage_publish_delta",
        name="Storage publish delta",
        unit="%",
    ),
    "fan_publish_delta_rpm": SettingSpec(
        key="fan_publish_delta_rpm",
        default=100.0,
        minimum=25.0,
        maximum=1000.0,
        step=25.0,
        entity_id="number.dh_pve_fan_publish_delta",
        name="Fan publish delta",
        unit="rpm",
    ),
    "gpu_publish_delta": SettingSpec(
        key="gpu_publish_delta",
        default=5.0,
        minimum=1.0,
        maximum=25.0,
        step=1.0,
        entity_id="number.dh_pve_gpu_publish_delta",
        name="GPU publish delta",
        unit="%",
    ),
}


class RuntimeSettings:
    def __init__(self, values: dict[str, float] | None = None) -> None:
        self._values = {key: spec.default for key, spec in SETTING_SPECS.items()}
        if values:
            for key, value in values.items():
                self.apply(key, str(value))

    def get(self, key: str) -> float:
        if key not in SETTING_SPECS:
            raise RuntimeSettingError(f"unknown runtime setting: {key}")
        return self._values[key]

    def as_dict(self) -> dict[str, float]:
        return dict(self._values)

    def apply(self, key: str, raw_value: str) -> float:
        spec = SETTING_SPECS.get(key)
        if spec is None:
            raise RuntimeSettingError(f"unknown runtime setting: {key}")

        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise RuntimeSettingError(f"{key} must be numeric") from exc

        if not math.isfinite(value):
            raise RuntimeSettingError(f"{key} must be finite")
        if not spec.minimum <= value <= spec.maximum:
            raise RuntimeSettingError(
                f"{key} must be between {spec.minimum} and {spec.maximum}"
            )

        self._values[key] = value
        return value
