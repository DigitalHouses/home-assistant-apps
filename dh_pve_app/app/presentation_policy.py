from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from numbers import Real
from typing import Mapping

from .disk_health import disk_temperature_limits
from .presentation import PublicationProfile


@dataclass(frozen=True)
class ThresholdRule:
    key: str
    decision_window_seconds: float
    high_enter: float | None
    high_exit: float | None
    critical_enter: float | None = None
    critical_exit: float | None = None
    higher_is_worse: bool = True


@dataclass(frozen=True)
class ProfileChoice:
    profile: PublicationProfile
    reason: str | None
    averages: dict[str, float]


class ResourceProfileSelector:
    """Choose one resource profile from rolling averaged numeric signals.

    Numeric escalation is intentionally disabled until each rule has observed
    a complete decision window. Immediate discrete flags bypass that delay.
    """

    def __init__(
        self,
        rules: tuple[ThresholdRule, ...],
        *,
        immediate_high: tuple[str, ...] = (),
        immediate_critical: tuple[str, ...] = (),
    ) -> None:
        self.rules = rules
        self.immediate_high = immediate_high
        self.immediate_critical = immediate_critical
        self.profile = PublicationProfile.NORMAL
        self._samples: dict[str, deque[tuple[float, float]]] = defaultdict(deque)
        self._first_seen: dict[str, float] = {}

    @staticmethod
    def _numeric(value: object) -> bool:
        return isinstance(value, Real) and not isinstance(value, bool)

    @staticmethod
    def _crosses(value: float, threshold: float | None, *, higher: bool) -> bool:
        if threshold is None:
            return False
        return value >= threshold if higher else value <= threshold

    def _add(self, rule: ThresholdRule, now: float, value: object) -> None:
        if value is None:
            return
        if not self._numeric(value):
            raise TypeError(f"profile metric {rule.key!r} must be numeric or None")
        samples = self._samples[rule.key]
        samples.append((now, float(value)))
        self._first_seen.setdefault(rule.key, now)
        cutoff = now - float(rule.decision_window_seconds)
        while samples and samples[0][0] < cutoff:
            samples.popleft()

    def _average(self, key: str) -> float | None:
        samples = self._samples.get(key)
        if not samples:
            return None
        return sum(value for _at, value in samples) / len(samples)

    def _ready(self, rule: ThresholdRule, now: float) -> bool:
        first = self._first_seen.get(rule.key)
        return first is not None and now - first >= float(rule.decision_window_seconds)

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
                self._add(rule, now, metrics.get(rule.key))

        averages = {
            rule.key: round(value, 3)
            for rule in self.rules
            if (value := self._average(rule.key)) is not None
        }

        for key in self.immediate_critical:
            if flags.get(key) is True:
                self.profile = PublicationProfile.CRITICAL
                return ProfileChoice(self.profile, key, averages)

        ready_rules = [rule for rule in self.rules if self._ready(rule, now)]

        for rule in ready_rules:
            value = averages.get(rule.key)
            if value is not None and self._crosses(
                value, rule.critical_enter, higher=rule.higher_is_worse
            ):
                self.profile = PublicationProfile.CRITICAL
                return ProfileChoice(self.profile, rule.key, averages)

        for key in self.immediate_high:
            if flags.get(key) is True:
                self.profile = PublicationProfile.HIGH
                return ProfileChoice(self.profile, key, averages)

        # A profile entered through an immediate flag must remain detailed until
        # the numeric recovery window is mature enough to make a safe downgrade.
        if self.profile in {PublicationProfile.HIGH, PublicationProfile.CRITICAL}:
            if self.rules and not ready_rules:
                return ProfileChoice(self.profile, "recovery_pending", averages)

        if self.profile is PublicationProfile.CRITICAL:
            for rule in ready_rules:
                value = averages.get(rule.key)
                if value is not None and self._crosses(
                    value, rule.critical_exit, higher=rule.higher_is_worse
                ):
                    return ProfileChoice(self.profile, rule.key, averages)

            for rule in ready_rules:
                value = averages.get(rule.key)
                if value is not None and self._crosses(
                    value, rule.high_enter, higher=rule.higher_is_worse
                ):
                    self.profile = PublicationProfile.HIGH
                    return ProfileChoice(self.profile, rule.key, averages)

            self.profile = PublicationProfile.NORMAL
            return ProfileChoice(self.profile, "recovered", averages)

        if self.profile is PublicationProfile.HIGH:
            for rule in ready_rules:
                value = averages.get(rule.key)
                if value is not None and self._crosses(
                    value, rule.high_exit, higher=rule.higher_is_worse
                ):
                    return ProfileChoice(self.profile, rule.key, averages)

            self.profile = PublicationProfile.NORMAL
            return ProfileChoice(self.profile, "recovered", averages)

        for rule in ready_rules:
            value = averages.get(rule.key)
            if value is not None and self._crosses(
                value, rule.high_enter, higher=rule.higher_is_worse
            ):
                self.profile = PublicationProfile.HIGH
                return ProfileChoice(self.profile, rule.key, averages)

        self.profile = PublicationProfile.NORMAL
        return ProfileChoice(self.profile, None, averages)


def cpu_profile_selector() -> ResourceProfileSelector:
    return ResourceProfileSelector(
        (
            ThresholdRule("usage", 60.0, 75.0, 60.0, 95.0, 85.0),
            ThresholdRule("temperature", 60.0, 80.0, 75.0, 90.0, 85.0),
        ),
        immediate_critical=("throttling",),
    )


def memory_profile_selector() -> ResourceProfileSelector:
    return ResourceProfileSelector(
        (ThresholdRule("usage", 120.0, 92.0, 88.0, 97.0, 94.0),)
    )


def disk_profile_selector(disk_type: str | None) -> ResourceProfileSelector:
    warning, critical = disk_temperature_limits(disk_type)
    return ResourceProfileSelector(
        (
            ThresholdRule(
                "temperature",
                180.0,
                warning,
                max(0.0, warning - 5.0),
                critical,
                max(0.0, critical - 5.0),
            ),
        )
    )


def gpu_profile_selector() -> ResourceProfileSelector:
    return ResourceProfileSelector(
        (
            ThresholdRule("temperature", 60.0, 75.0, 70.0, 85.0, 80.0),
            ThresholdRule("load", 60.0, 20.0, 10.0),
        )
    )


def ups_profile_selector() -> ResourceProfileSelector:
    return ResourceProfileSelector(
        (ThresholdRule("load", 30.0, 80.0, 70.0, 95.0, 90.0),),
        immediate_high=("on_battery", "bypass"),
        immediate_critical=("low_battery", "overload"),
    )
