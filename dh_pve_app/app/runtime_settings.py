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


# Runtime settings exposed to Home Assistant are collector controls only.
# Presentation thresholds/windows live in the adaptive presentation policy and
# are intentionally not duplicated as HA number entities.
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
        default=60.0,
        minimum=10.0,
        maximum=300.0,
        step=5.0,
        entity_id="number.dh_pve_disk_poll_interval",
        name="Disk poll interval",
        unit="s",
    ),
}

# Values from pre-adaptive installations may remain in runtime.json. They are
# accepted only while loading persisted state, then disappear on the next save.
LEGACY_SETTING_KEYS = frozenset(
    {
        "cpu_publish_delta",
        "memory_publish_delta",
        "temperature_publish_delta",
        "storage_publish_delta",
        "fan_publish_delta_rpm",
        "gpu_publish_delta",
    }
)


class RuntimeSettings:
    def __init__(self, values: dict[str, float] | None = None) -> None:
        self._values = {key: spec.default for key, spec in SETTING_SPECS.items()}
        if values:
            for key, value in values.items():
                if key in LEGACY_SETTING_KEYS:
                    continue
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
