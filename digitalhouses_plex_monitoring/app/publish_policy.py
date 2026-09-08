from __future__ import annotations

from dataclasses import dataclass

from .models import MonitorSnapshot


@dataclass(frozen=True)
class PublishDecision:
    publish: bool
    reasons: tuple[str, ...]


class PublishPolicy:
    def __init__(
        self,
        cpu_change_threshold: float,
        high_load_threshold: float,
        high_load_publish_interval_seconds: float,
    ) -> None:
        self.cpu_change_threshold = float(cpu_change_threshold)
        self.high_load_threshold = float(high_load_threshold)
        self.high_load_publish_interval_seconds = float(
            high_load_publish_interval_seconds
        )
        self._last_snapshot: MonitorSnapshot | None = None
        self._last_time: float | None = None

    @staticmethod
    def _event_key(snapshot: MonitorSnapshot) -> tuple[object, ...]:
        a = snapshot.activity
        return (
            a.plex_server_running,
            a.scanner_running,
            a.credits_detection,
            a.intro_detection,
            a.thumbnail_generation,
            a.transcoder_running,
            a.activity,
            a.scanner_actions,
            snapshot.collector_status,
        )

    @staticmethod
    def _current_cpu(snapshot: MonitorSnapshot) -> tuple[float, float, float]:
        return (
            snapshot.cpu.total.current,
            snapshot.cpu.scanner.current,
            snapshot.cpu.transcoder.current,
        )

    def evaluate(
        self,
        snapshot: MonitorSnapshot,
        now: float,
        *,
        force: bool = False,
    ) -> PublishDecision:
        reasons: list[str] = []
        previous = self._last_snapshot

        if previous is None:
            reasons.append("startup")
        if force:
            reasons.append("force")

        if previous is not None:
            if self._event_key(snapshot) != self._event_key(previous):
                reasons.append("activity_change")

            old_cpus = self._current_cpu(previous)
            new_cpus = self._current_cpu(snapshot)
            for label, old, new in zip(
                ("cpu", "scanner_cpu", "transcoder_cpu"),
                old_cpus,
                new_cpus,
            ):
                if (old == 0.0) != (new == 0.0):
                    reasons.append(f"{label}_zero_transition")
                elif abs(new - old) >= self.cpu_change_threshold:
                    reasons.append(f"{label}_change")

            old_high = previous.cpu.total.current >= self.high_load_threshold
            new_high = snapshot.cpu.total.current >= self.high_load_threshold
            if old_high != new_high:
                reasons.append(
                    "high_load_enter" if new_high else "high_load_exit"
                )
            elif new_high and self._last_time is not None:
                if now - self._last_time >= self.high_load_publish_interval_seconds:
                    reasons.append("high_load_interval")

        # Preserve order while de-duplicating reasons.
        unique = tuple(dict.fromkeys(reasons))
        return PublishDecision(bool(unique), unique)

    def mark_published(
        self,
        snapshot: MonitorSnapshot,
        now: float,
    ) -> None:
        self._last_snapshot = snapshot
        self._last_time = float(now)
