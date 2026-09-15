from __future__ import annotations

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


# Collection cadence is an internal architecture contract. There are currently
# no runtime number settings exposed through MQTT Discovery.
SETTING_SPECS: dict[str, SettingSpec] = {}

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

    def apply(self, key: str, raw_value: str) -> float:
        spec = SETTING_SPECS.get(key)
        if spec is None:
            raise RuntimeSettingError(f"unknown runtime setting: {key}")
        raise AssertionError("unreachable: no active runtime settings")
