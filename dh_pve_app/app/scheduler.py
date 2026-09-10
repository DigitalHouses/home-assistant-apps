from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Task:
    interval_seconds: float
    next_due: float


class Scheduler:
    def __init__(self) -> None:
        self._tasks: dict[str, _Task] = {}

    @staticmethod
    def _validated_interval(interval_seconds: float) -> float:
        value = float(interval_seconds)
        if value <= 0:
            raise ValueError("interval_seconds must be > 0")
        return value

    def add(
        self,
        name: str,
        *,
        interval_seconds: float,
        now: float,
        run_immediately: bool = False,
    ) -> None:
        if not name:
            raise ValueError("task name must not be empty")
        if name in self._tasks:
            raise ValueError(f"task already exists: {name}")
        interval = self._validated_interval(interval_seconds)
        next_due = float(now) if run_immediately else float(now) + interval
        self._tasks[name] = _Task(interval_seconds=interval, next_due=next_due)

    def due(self, now: float) -> tuple[str, ...]:
        current = float(now)
        return tuple(
            name for name, task in self._tasks.items()
            if task.next_due <= current
        )

    def mark_run(self, name: str, *, now: float) -> None:
        task = self._tasks[name]
        task.next_due = float(now) + task.interval_seconds

    def set_interval(
        self,
        name: str,
        interval_seconds: float,
        *,
        now: float,
    ) -> None:
        task = self._tasks[name]
        interval = self._validated_interval(interval_seconds)
        task.interval_seconds = interval
        task.next_due = float(now) + interval
