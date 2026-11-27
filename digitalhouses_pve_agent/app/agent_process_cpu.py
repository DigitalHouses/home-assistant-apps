"""One-core-normalized CPU use of the agent service, independent of MQTT.

Read the dedicated systemd cgroup v2 counter including child processes.
100% is one continuously busy core; percentages above 100 are possible.
"""
from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Callable


def service_cpu_reader(
    *, membership: Path = Path("/proc/self/cgroup"),
    root: Path = Path("/sys/fs/cgroup"),
) -> Callable[[], float | None]:
    """Never count the host, a login session, or another systemd service."""
    try:
        groups = membership.read_text().splitlines()
        path = next(line[3:] for line in groups if line.startswith("0::"))
        group = Path(path)
        if (not group.is_absolute() or ".." in group.parts
                or group.name != "digitalhouses_pve_agent.service"):
            return lambda: None
        stat = root / group.relative_to("/") / "cpu.stat"
    except (OSError, ValueError, StopIteration):
        return lambda: None

    def read() -> float | None:
        try:
            for line in stat.read_text().splitlines():
                key, value = line.split()
                if key == "usage_usec":
                    microseconds = int(value)
                    return microseconds / 1_000_000 if microseconds >= 0 else None
        except (OSError, ValueError):
            pass
        return None

    return read


class AgentProcessCpu:
    def __init__(
        self, *,
        high: float = 80.0, high_seconds: float = 300.0,
        low: float = 40.0, low_seconds: float = 120.0,
        max_gap: float = 35.0,
        cpu_reader: Callable[[], float | None] | None = None,
    ) -> None:
        self._cpu_reader = cpu_reader if cpu_reader is not None else service_cpu_reader()
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
        cpu_time = self._cpu_reader() if cpu_time is None else float(cpu_time)
        if cpu_time is None or not math.isfinite(now) or not math.isfinite(cpu_time):
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
            "measurement_scope": "service_cgroup_v2",
            "overloaded": self.overloaded if self.usage_percent is not None else None,
            "high_threshold_percent": self.high,
            "high_seconds": self.high_seconds,
            "recovery_threshold_percent": self.low,
            "recovery_seconds": self.low_seconds,
        }
