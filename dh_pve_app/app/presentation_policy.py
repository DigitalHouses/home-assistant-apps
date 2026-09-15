from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .disk_health import disk_temperature_limits
from .presentation import PublicationProfile
from .runtime_windows import RollingAverage


@dataclass(frozen=True)
class ThresholdRule:
    key: str
    decision_window_seconds: float
    threshold: float
    higher_is_worse: bool = True


@dataclass(frozen=True)
class ProfileChoice:
    profile: PublicationProfile
    reason: str | None
    averages: dict[str, float]


class ResourceProfileSelector:
    """Choose NORMAL or DETAIL from independent rolling decision averages."""

    def __init__(
        self,
        rules: tuple[ThresholdRule, ...],
        *,
        immediate_detail: tuple[str, ...] = (),
    ) -> None:
        self.rules = rules
        self.immediate_detail = immediate_detail
        self.profile = PublicationProfile.NORMAL
        self._windows = {
            rule.key: RollingAverage(rule.decision_window_seconds)
            for rule in rules
        }
        self._rule_profiles = {
            rule.key: PublicationProfile.NORMAL
            for rule in rules
        }
        self._reason: str | None = None

    @staticmethod
    def _next_profile(
        current: PublicationProfile,
        value: float,
        threshold: float,
        *,
        higher_is_worse: bool,
    ) -> PublicationProfile:
        if higher_is_worse:
            if value > threshold:
                return PublicationProfile.DETAIL
            if value < threshold:
                return PublicationProfile.NORMAL
        else:
            if value < threshold:
                return PublicationProfile.DETAIL
            if value > threshold:
                return PublicationProfile.NORMAL
        return current

    def observe(
        self,
        *,
        now: float,
        metrics: Mapping[str, object],
        flags: Mapping[str, bool] | None = None,
    ) -> ProfileChoice:
        now = float(now)
        flags = flags or {}
        for rule in self.rules:
            if rule.key in metrics:
                self._windows[rule.key].observe(now, metrics.get(rule.key))

        averages: dict[str, float] = {}
        valid_rules = 0
        for rule in self.rules:
            value = self._windows[rule.key].average(now)
            if value is None:
                continue
            valid_rules += 1
            averages[rule.key] = round(value, 3)
            self._rule_profiles[rule.key] = self._next_profile(
                self._rule_profiles[rule.key],
                value,
                float(rule.threshold),
                higher_is_worse=rule.higher_is_worse,
            )

        for key in self.immediate_detail:
            if flags.get(key) is True:
                self.profile = PublicationProfile.DETAIL
                self._reason = key
                return ProfileChoice(self.profile, self._reason, averages)

        # No valid decision average means no transition. This is deliberately
        # different from treating unavailable telemetry as zero.
        if valid_rules == 0:
            return ProfileChoice(self.profile, self._reason, averages)

        detail_reason = next(
            (
                rule.key
                for rule in self.rules
                if self._rule_profiles[rule.key] is PublicationProfile.DETAIL
            ),
            None,
        )
        target = (
            PublicationProfile.DETAIL
            if detail_reason is not None
            else PublicationProfile.NORMAL
        )
        if target is PublicationProfile.DETAIL:
            self.profile = target
            self._reason = detail_reason
        elif self.profile is PublicationProfile.DETAIL:
            self.profile = target
            self._reason = "recovered"
        else:
            self.profile = target
            self._reason = None
        return ProfileChoice(self.profile, self._reason, averages)


def cpu_profile_selector() -> ResourceProfileSelector:
    return ResourceProfileSelector(
        (
            ThresholdRule("usage", 60.0, 75.0),
            ThresholdRule("temperature", 60.0, 80.0),
        ),
        immediate_detail=("throttling",),
    )


def memory_profile_selector() -> ResourceProfileSelector:
    return ResourceProfileSelector((ThresholdRule("usage", 60.0, 92.0),))


def disk_profile_selector(disk_type: str | None) -> ResourceProfileSelector:
    warning, _critical = disk_temperature_limits(disk_type)
    return ResourceProfileSelector(
        (ThresholdRule("temperature", 300.0, warning),)
    )


def gpu_profile_selector() -> ResourceProfileSelector:
    return ResourceProfileSelector(
        (
            ThresholdRule("temperature", 300.0, 75.0),
            ThresholdRule("load", 300.0, 20.0),
        )
    )


def ups_profile_selector() -> ResourceProfileSelector:
    return ResourceProfileSelector(
        (ThresholdRule("load", 60.0, 80.0),),
        immediate_detail=("low_battery", "overload", "on_battery", "bypass"),
    )
