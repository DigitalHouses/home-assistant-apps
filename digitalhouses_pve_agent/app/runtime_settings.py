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


def _spec(
    key: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
    step: float,
    entity_id: str,
    name: str,
    unit: str,
) -> SettingSpec:
    return SettingSpec(
        key=key,
        default=float(default),
        minimum=float(minimum),
        maximum=float(maximum),
        step=float(step),
        entity_id=entity_id,
        name=name,
        unit=unit,
    )


SETTING_SPECS: dict[str, SettingSpec] = {
    "storage_percent_used_threshold": _spec(
        "storage_percent_used_threshold",
        default=80,
        minimum=0,
        maximum=98,
        step=1,
        entity_id="number.dh_pve_agent_storage_percent_used_threshold",
        name="Storage used threshold",
        unit="%",
    ),
    "cpu_temperature_threshold": _spec(
        "cpu_temperature_threshold",
        default=90,
        minimum=0,
        maximum=110,
        step=1,
        entity_id="number.dh_pve_agent_cpu_temperature_threshold",
        name="CPU temperature threshold",
        unit="°C",
    ),
    "hdd_temperature_threshold": _spec(
        "hdd_temperature_threshold",
        default=45,
        minimum=0,
        maximum=70,
        step=1,
        entity_id="number.dh_pve_agent_hdd_temperature_threshold",
        name="HDD temperature threshold",
        unit="°C",
    ),
    "ssd_temperature_threshold": _spec(
        "ssd_temperature_threshold",
        default=75,
        minimum=0,
        maximum=90,
        step=1,
        entity_id="number.dh_pve_agent_ssd_temperature_threshold",
        name="SSD temperature threshold",
        unit="°C",
    ),
    "nvme_temperature_threshold": _spec(
        "nvme_temperature_threshold",
        default=80,
        minimum=0,
        maximum=110,
        step=1,
        entity_id="number.dh_pve_agent_nvme_temperature_threshold",
        name="NVMe temperature threshold",
        unit="°C",
    ),
    "gpu_temperature_threshold": _spec(
        "gpu_temperature_threshold",
        default=85,
        minimum=0,
        maximum=110,
        step=1,
        entity_id="number.dh_pve_agent_gpu_temperature_threshold",
        name="GPU temperature threshold",
        unit="°C",
    ),
}

# Values from earlier installations may remain in runtime.json. They are
# accepted only while loading persisted state, then disappear on the next save.
LEGACY_SETTING_KEYS = frozenset(
    {
        "fast_poll_interval_seconds",
        "disk_poll_interval_seconds",
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

    @staticmethod
    def _validated(spec: SettingSpec, raw_value: str) -> float:
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise RuntimeSettingError(f"invalid value for {spec.key}: {raw_value!r}") from exc

        if not math.isfinite(value):
            raise RuntimeSettingError(f"non-finite value for {spec.key}: {raw_value!r}")
        if value < spec.minimum or value > spec.maximum:
            raise RuntimeSettingError(
                f"value for {spec.key} must be between {spec.minimum:g} and {spec.maximum:g}"
            )

        steps = (value - spec.minimum) / spec.step
        nearest = round(steps)
        if not math.isclose(steps, nearest, rel_tol=0.0, abs_tol=1e-9):
            raise RuntimeSettingError(
                f"value for {spec.key} must align to step {spec.step:g}"
            )

        normalized = spec.minimum + nearest * spec.step
        return round(float(normalized), 10)

    def apply(self, key: str, raw_value: str) -> float:
        spec = SETTING_SPECS.get(key)
        if spec is None:
            raise RuntimeSettingError(f"unknown runtime setting: {key}")
        value = self._validated(spec, raw_value)
        self._values[key] = value
        return value
