from __future__ import annotations

from collections import deque
from typing import Sequence

from .models import CpuGroupMetrics, CpuMetrics, ProcessSample


def group_current_cpu(
    processes: Sequence[ProcessSample],
) -> tuple[float, float, float]:
    total = 0.0
    scanner = 0.0
    transcoder = 0.0
    for process in processes:
        name = process.name.casefold()
        if not name.startswith("plex"):
            continue
        total += process.cpu_percent
        if "media scanner" in name:
            scanner += process.cpu_percent
        if "transcoder" in name:
            transcoder += process.cpu_percent
    return total, scanner, transcoder


class RollingCpuMetrics:
    def __init__(self, window_seconds: float) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.window_seconds = float(window_seconds)
        self._samples: deque[tuple[float, float, float, float]] = deque()

    def update(
        self,
        now: float,
        total: float,
        scanner: float,
        transcoder: float,
    ) -> CpuMetrics:
        self._samples.append(
            (float(now), float(total), float(scanner), float(transcoder))
        )
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

        def group(index: int, current: float) -> CpuGroupMetrics:
            values = [sample[index] for sample in self._samples]
            return CpuGroupMetrics(
                current=float(current),
                average=sum(values) / len(values),
                maximum=max(values),
            )

        return CpuMetrics(
            total=group(1, total),
            scanner=group(2, scanner),
            transcoder=group(3, transcoder),
        )
