from __future__ import annotations

import math
from collections import deque
from numbers import Real

from .presentation import PublicationProfile


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


class RollingAverage:
    """Time-windowed average over valid numeric samples only."""

    def __init__(self, window_seconds: float) -> None:
        window = _finite_number(window_seconds)
        if window is None or window <= 0.0:
            raise ValueError("window_seconds must be a finite number > 0")
        self.window_seconds = window
        self._samples: deque[tuple[float, float]] = deque()

    @staticmethod
    def _now(value: float) -> float:
        now = _finite_number(value)
        if now is None:
            raise ValueError("now must be a finite number")
        return now

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def observe(self, now: float, value: object) -> None:
        current = self._now(now)
        self._prune(current)
        sample = _finite_number(value)
        if sample is None:
            return
        self._samples.append((current, sample))

    def average(self, now: float) -> float | None:
        current = self._now(now)
        self._prune(current)
        if not self._samples:
            return None
        return sum(value for _timestamp, value in self._samples) / len(self._samples)


class TwoProfileDecision:
    """Strict NORMAL/DETAIL state transition driven by one averaged metric."""

    def __init__(
        self,
        threshold: float,
        *,
        initial: PublicationProfile = PublicationProfile.NORMAL,
    ) -> None:
        value = _finite_number(threshold)
        if value is None:
            raise ValueError("threshold must be a finite number")
        if initial not in (PublicationProfile.NORMAL, PublicationProfile.DETAIL):
            raise ValueError("initial profile must be NORMAL or DETAIL")
        self.threshold = value
        self.profile = initial

    def update(self, value: object) -> PublicationProfile:
        sample = _finite_number(value)
        if sample is None:
            return self.profile
        if sample > self.threshold:
            self.profile = PublicationProfile.DETAIL
        elif sample < self.threshold:
            self.profile = PublicationProfile.NORMAL
        return self.profile
