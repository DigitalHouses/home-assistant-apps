from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta


class TestScheduleError(ValueError):
    """Raised when a battery-test schedule is invalid."""


_TIME_RE = re.compile(r"^(\d{2}):(\d{2})$")
_ELIGIBLE_WINDOW = timedelta(hours=1)


def parse_preferred_time(value: str) -> time:
    match = _TIME_RE.fullmatch(value.strip()) if isinstance(value, str) else None
    if match is None:
        raise TestScheduleError("Время теста должно быть в формате HH:MM.")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise TestScheduleError("Некорректное локальное время теста.")
    return time(hour=hour, minute=minute)


@dataclass(frozen=True)
class TestSchedule:
    interval_days: int
    preferred_time: str

    def __post_init__(self) -> None:
        if isinstance(self.interval_days, bool) or not isinstance(self.interval_days, int):
            raise TestScheduleError("Периодичность теста должна быть целым числом дней.")
        if self.interval_days < 0:
            raise TestScheduleError("Периодичность теста не может быть отрицательной.")
        parsed = parse_preferred_time(self.preferred_time)
        object.__setattr__(self, "preferred_time", parsed.strftime("%H:%M"))


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TestScheduleError("Расписание тестов требует локальное timezone-aware время.")


def _local_at(day, preferred: time, tzinfo) -> datetime:
    return datetime.combine(day, preferred, tzinfo=tzinfo)


def next_scheduled_test(
    schedule: TestSchedule,
    anchor: datetime,
) -> datetime | None:
    """Return the first scheduled local run after the persisted anchor.

    The anchor is the last accepted scheduled run, or the initial schedule anchor
    created when automatic testing is first configured. A zero-day interval
    disables automatic execution.
    """
    _require_aware(anchor)
    if schedule.interval_days == 0:
        return None
    preferred = parse_preferred_time(schedule.preferred_time)
    target_day = anchor.date() + timedelta(days=schedule.interval_days)
    return _local_at(target_day, preferred, anchor.tzinfo)


def _eligible_now(
    *,
    now: datetime,
    schedule: TestSchedule,
    anchor: datetime,
) -> bool:
    due = next_scheduled_test(schedule, anchor)
    if due is None or now < due:
        return False

    preferred = parse_preferred_time(schedule.preferred_time)
    window_start = _local_at(now.date(), preferred, now.tzinfo)
    window_end = window_start + _ELIGIBLE_WINDOW
    return window_start <= now < window_end


def choose_scheduled_test(
    *,
    now: datetime,
    quick_schedule: TestSchedule,
    quick_anchor: datetime,
    deep_schedule: TestSchedule,
    deep_anchor: datetime,
    safe_to_test: bool,
) -> str | None:
    """Return the battery test eligible to start in the current local window.

    Deep has priority whenever both test types are eligible. The function is
    intentionally pure and never advances anchors; callers advance an anchor
    only after an accepted scheduled execution.
    """
    _require_aware(now)
    _require_aware(quick_anchor)
    _require_aware(deep_anchor)
    if not safe_to_test:
        return None

    deep_due = _eligible_now(
        now=now,
        schedule=deep_schedule,
        anchor=deep_anchor,
    )
    quick_due = _eligible_now(
        now=now,
        schedule=quick_schedule,
        anchor=quick_anchor,
    )

    if deep_due:
        return "deep"
    if quick_due:
        return "quick"
    return None
