from __future__ import annotations

from dataclasses import dataclass

from .presentation import PublicationProfile
from .runtime_windows import RollingAverage


@dataclass(frozen=True)
class ProfileChoice:
    profile: PublicationProfile
    reason: str | None
    cpu_average: float | None


class PlexProfileSelector:
    """Choose NORMAL/DETAIL/PLAYBACK without changing acquisition cadence."""

    def __init__(
        self,
        *,
        high_cpu_threshold: float = 80.0,
        decision_window_seconds: float = 60.0,
    ) -> None:
        self.high_cpu_threshold = float(high_cpu_threshold)
        self._cpu = RollingAverage(decision_window_seconds)
        self.profile = PublicationProfile.NORMAL
        self.reason: str | None = None

    def observe(
        self,
        *,
        now: float,
        cpu_percent: object,
        scanner_running: bool,
        transcoder_running: bool,
        playback_active: bool,
    ) -> ProfileChoice:
        self._cpu.observe(now, cpu_percent)
        average = self._cpu.average(now)

        if transcoder_running:
            self.profile = PublicationProfile.PLAYBACK
            self.reason = "transcoder_running"
            return ProfileChoice(self.profile, self.reason, average)

        if playback_active:
            self.profile = PublicationProfile.PLAYBACK
            self.reason = "playback_active"
            return ProfileChoice(self.profile, self.reason, average)

        if scanner_running:
            self.profile = PublicationProfile.DETAIL
            self.reason = "scanner_running"
            return ProfileChoice(self.profile, self.reason, average)

        previous_profile = self.profile

        if average is None:
            return ProfileChoice(self.profile, self.reason, None)

        if average > self.high_cpu_threshold:
            self.profile = PublicationProfile.DETAIL
            self.reason = "high_cpu"
        elif average < self.high_cpu_threshold:
            recovered = previous_profile is not PublicationProfile.NORMAL
            self.profile = PublicationProfile.NORMAL
            self.reason = "recovered" if recovered else None

        return ProfileChoice(self.profile, self.reason, average)
