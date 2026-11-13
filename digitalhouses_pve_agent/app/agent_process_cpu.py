"""One-core-normalized CPU use of the agent process, independent of MQTT.

Uses process CPU time (all threads), not machine-wide CPU utilization.
100% is one continuously busy core; percentages above 100 are possible.
"""
from __future__ import annotations

import math
import time


class AgentProcessCpu:
    def __init__(
        self, *,
        high: float = 80.0, high_seconds: float = 300.0,
        low: float = 40.0, low_seconds: float = 120.0,
        max_gap: float = 35.0,
    ) -> None:
        self.high = high
        self.low = low
        self.high_seconds = high_seconds
        self.low_seconds = low_seconds
        self.max_gap = max_gap
        self.usage_percent: float | None = None
        self.overloaded = False
        self._previous: tuple[float, float] | None = None
        self._high_since: float | None = None
        self._low_since: float | None = None

    def observe(self, *, now: float | None = None, cpu_time: float | None = None) -> float | None:
        now = time.monotonic() if now is None else float(now)
        cpu_time = time.process_time() if cpu_time is None else float(cpu_time)
        if not math.isfinite(now) or not math.isfinite(cpu_time):
            self._previous = None
            self._high_since = self._low_since = None
            self.usage_percent = None
            return None
        previous = self._previous
        self._previous = (now, cpu_time)
        if previous is None:
            return None
        elapsed = now - previous[0]
        cpu_delta = cpu_time - previous[1]
        if not (0 < elapsed <= self.max_gap and cpu_delta >= 0):
            self._high_since = self._low_since = None
            self.usage_percent = None
            return None
        usage = max(0.0, cpu_delta / elapsed * 100.0)
        self.usage_percent = round(usage, 2)
        if self.overloaded:
            self._high_since = None
            if usage < self.low:
                if self._low_since is None:
                    self._low_since = now
                elif now - self._low_since >= self.low_seconds:
                    self.overloaded = False
                    self._low_since = None
            else:
                self._low_since = None
        else:
            self._low_since = None
            if usage > self.high:
                if self._high_since is None:
                    self._high_since = now
                elif now - self._high_since >= self.high_seconds:
                    self.overloaded = True
                    self._high_since = None
            else:
                self._high_since = None
        return self.usage_percent

    def snapshot(self) -> dict[str, object]:
        return {
            "usage_percent": self.usage_percent,
            "overloaded": self.overloaded if self.usage_percent is not None else None,
            "high_threshold_percent": self.high,
            "high_seconds": self.high_seconds,
            "recovery_threshold_percent": self.low,
            "recovery_seconds": self.low_seconds,
        }
