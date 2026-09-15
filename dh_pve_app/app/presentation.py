from __future__ import annotations

"""Recorder-facing publication primitives for dh_pve_app."""

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from typing import Mapping


class PublicationProfile(str, Enum):
    NORMAL = "normal"
    DETAIL = "detail"


@dataclass(frozen=True)
class ProfileWindows:
    normal_seconds: float = 900.0
    detail_seconds: float = 300.0

    def seconds(self, profile: PublicationProfile) -> float:
        if profile is PublicationProfile.NORMAL:
            return float(self.normal_seconds)
        if profile is PublicationProfile.DETAIL:
            return float(self.detail_seconds)
        raise ValueError(f"unsupported publication profile: {profile!r}")


@dataclass(frozen=True)
class GroupDecision:
    publish: bool
    profile: PublicationProfile
    reason: str | None
    values: dict[str, object]
    profile_changed: bool = False


class AdaptiveGroup:
    """Average acquired samples without ever changing acquisition cadence.

    Profile selection is external. The group only controls Recorder-facing
    publication windows, immediate semantic changes and manual snapshots.
    """

    def __init__(
        self,
        *,
        windows: ProfileWindows | None = None,
        initial_profile: PublicationProfile = PublicationProfile.NORMAL,
        source_interval_seconds: float = 0.0,
        round_digits: int = 2,
    ) -> None:
        self.windows = windows or ProfileWindows()
        self.profile = initial_profile
        self.source_interval_seconds = max(0.0, float(source_interval_seconds))
        self.round_digits = int(round_digits)
        self._seen = False
        self._bucket_started_at: float | None = None
        self._bucket: dict[str, list[float]] = defaultdict(list)
        self._last_observed_discrete: dict[str, object] = {}
        self._last_published_values: dict[str, object] | None = None

    @staticmethod
    def _numeric(value: object) -> bool:
        return isinstance(value, Real) and not isinstance(value, bool)

    def _add_samples(self, continuous: Mapping[str, object]) -> None:
        for key, value in continuous.items():
            if value is None:
                continue
            if not self._numeric(value):
                raise TypeError(f"continuous value {key!r} must be numeric or None")
            self._bucket[str(key)].append(float(value))

    def _averages(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, samples in self._bucket.items():
            if samples:
                result[key] = round(sum(samples) / len(samples), self.round_digits)
        return result

    def _current_values(self, continuous: Mapping[str, object]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in continuous.items():
            if value is None:
                continue
            if not self._numeric(value):
                raise TypeError(f"continuous value {key!r} must be numeric or None")
            result[str(key)] = round(float(value), self.round_digits)
        return result

    @staticmethod
    def _combined(
        continuous_values: Mapping[str, object],
        discrete: Mapping[str, object],
    ) -> dict[str, object]:
        return {**dict(continuous_values), **dict(discrete)}

    def _mark_published(self, values: Mapping[str, object]) -> None:
        self._last_published_values = dict(values)

    def _reset_bucket(self, now: float) -> None:
        self._bucket.clear()
        self._bucket_started_at = float(now)

    def _effective_window(self) -> float:
        return max(
            self.windows.seconds(self.profile),
            self.source_interval_seconds,
        )

    def observe(
        self,
        *,
        now: float,
        continuous: Mapping[str, object],
        discrete: Mapping[str, object] | None = None,
        requested_profile: PublicationProfile | None = None,
        force: bool = False,
        manual: bool = False,
    ) -> GroupDecision:
        now = float(now)
        discrete_values = dict(discrete or {})
        if self._bucket_started_at is None:
            self._bucket_started_at = now
        self._add_samples(continuous)

        first = not self._seen
        previous_discrete = dict(self._last_observed_discrete)
        discrete_changed = self._seen and discrete_values != previous_discrete
        self._last_observed_discrete = discrete_values

        target_profile = requested_profile or self.profile
        profile_changed = target_profile is not self.profile
        if profile_changed:
            self.profile = target_profile

        averages = self._averages()

        if first:
            self._seen = True
            values = self._combined(averages, discrete_values)
            self._mark_published(values)
            self._reset_bucket(now)
            return GroupDecision(True, self.profile, "startup", values, profile_changed)

        if manual:
            values = self._combined(self._current_values(continuous), discrete_values)
            self._mark_published(values)
            return GroupDecision(True, self.profile, "manual_refresh", values, profile_changed)

        if force:
            values = self._combined(averages, discrete_values)
            self._mark_published(values)
            self._reset_bucket(now)
            return GroupDecision(True, self.profile, "force", values, profile_changed)

        if profile_changed:
            values = self._combined(averages, discrete_values)
            self._mark_published(values)
            self._reset_bucket(now)
            return GroupDecision(True, self.profile, "profile_transition", values, True)

        if discrete_changed:
            values = self._combined(averages, discrete_values)
            self._mark_published(values)
            return GroupDecision(True, self.profile, "change", values, False)

        elapsed = now - self._bucket_started_at
        if elapsed < self._effective_window():
            return GroupDecision(False, self.profile, None, {}, False)

        values = self._combined(averages, discrete_values)
        self._reset_bucket(now)
        if self._last_published_values == values:
            return GroupDecision(False, self.profile, None, {}, False)

        self._mark_published(values)
        return GroupDecision(
            True,
            self.profile,
            "average_window_complete",
            values,
            False,
        )
