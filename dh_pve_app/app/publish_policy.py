from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .runtime_settings import RuntimeSettings


@dataclass(frozen=True)
class MetricValue:
    value: Any
    policy: str


@dataclass(frozen=True)
class PublishDecision:
    publish: bool
    reasons: tuple[str, ...]


class PublishPolicy:
    _FIXED_THRESHOLDS = {
        "frequency_mhz": 100.0,
        "ups_percent": 1.0,
        "ups_voltage": 1.0,
        "ups_runtime_seconds": 60.0,
    }
    _SETTING_THRESHOLDS = {
        "cpu_percent": "cpu_publish_delta",
        "memory_percent": "memory_publish_delta",
        "temperature_c": "temperature_publish_delta",
        "storage_percent": "storage_publish_delta",
        "fan_rpm": "fan_publish_delta_rpm",
        "gpu_percent": "gpu_publish_delta",
    }
    _IMMEDIATE_POLICIES = {"discrete", "counter"}

    def __init__(self, settings: RuntimeSettings) -> None:
        self.settings = settings
        self._last_published: dict[str, MetricValue] | None = None

    def _threshold(self, policy: str) -> float | None:
        setting_key = self._SETTING_THRESHOLDS.get(policy)
        if setting_key is not None:
            return self.settings.get(setting_key)
        return self._FIXED_THRESHOLDS.get(policy)

    @staticmethod
    def _is_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def evaluate(
        self,
        snapshot: Mapping[str, MetricValue],
        *,
        force: bool = False,
    ) -> PublishDecision:
        reasons: list[str] = []
        previous = self._last_published

        if previous is None:
            reasons.append("startup")
        if force:
            reasons.append("force")

        if previous is not None:
            old_keys = set(previous)
            new_keys = set(snapshot)
            for key in sorted(old_keys ^ new_keys):
                reasons.append(f"{key}_inventory_change")

            for key in sorted(old_keys & new_keys):
                old = previous[key]
                new = snapshot[key]
                if old.policy != new.policy:
                    reasons.append(f"{key}_policy_change")
                    continue
                if old.value == new.value:
                    continue

                if new.policy in self._IMMEDIATE_POLICIES:
                    reasons.append(f"{key}_change")
                    continue

                threshold = self._threshold(new.policy)
                if threshold is None:
                    reasons.append(f"{key}_change")
                    continue

                if not self._is_number(old.value) or not self._is_number(new.value):
                    reasons.append(f"{key}_change")
                    continue

                old_number = float(old.value)
                new_number = float(new.value)
                if (old_number == 0.0) != (new_number == 0.0):
                    reasons.append(f"{key}_zero_transition")
                elif abs(new_number - old_number) >= threshold:
                    reasons.append(f"{key}_change")

        unique = tuple(dict.fromkeys(reasons))
        return PublishDecision(publish=bool(unique), reasons=unique)

    def mark_published(self, snapshot: Mapping[str, MetricValue]) -> None:
        self._last_published = dict(snapshot)

    def last_published(self) -> dict[str, MetricValue] | None:
        if self._last_published is None:
            return None
        return dict(self._last_published)
