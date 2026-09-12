from datetime import datetime, timedelta, timezone

import pytest

from app.ups_test_schedule import (
    TestSchedule,
    TestScheduleError,
    choose_scheduled_test,
    next_scheduled_test,
    parse_preferred_time,
)


TZ = timezone(timedelta(hours=5))


def dt(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def test_default_schedule_shape_supports_interval_and_local_time():
    quick = TestSchedule(interval_days=30, preferred_time="12:00")
    deep = TestSchedule(interval_days=180, preferred_time="13:00")

    assert quick.interval_days == 30
    assert quick.preferred_time == "12:00"
    assert deep.interval_days == 180
    assert deep.preferred_time == "13:00"


def test_parse_preferred_time_is_strict_hh_mm():
    assert parse_preferred_time("12:00").hour == 12
    assert parse_preferred_time("12:00").minute == 0

    for value in ("2:00", "24:00", "12:60", "night", "12:00:00"):
        with pytest.raises(TestScheduleError):
            parse_preferred_time(value)


def test_next_due_uses_persisted_anchor_and_survives_restart():
    schedule = TestSchedule(interval_days=30, preferred_time="12:00")
    persisted_anchor = dt(2026, 9, 13, 1, 30)

    first = next_scheduled_test(schedule, persisted_anchor)
    after_restart = next_scheduled_test(schedule, persisted_anchor)

    assert first == dt(2026, 10, 13, 12, 0)
    assert after_restart == first


def test_zero_days_disables_automatic_test():
    schedule = TestSchedule(interval_days=0, preferred_time="12:00")

    assert next_scheduled_test(schedule, dt(2026, 9, 13, 1, 30)) is None
    assert choose_scheduled_test(
        now=dt(2027, 1, 1, 12, 0),
        quick_schedule=schedule,
        quick_anchor=dt(2026, 1, 1, 12, 0),
        deep_schedule=TestSchedule(interval_days=0, preferred_time="13:00"),
        deep_anchor=dt(2026, 1, 1, 13, 0),
        safe_to_test=True,
    ) is None


def test_overdue_test_does_not_start_at_night_and_runs_in_next_local_window():
    quick = TestSchedule(interval_days=30, preferred_time="12:00")
    anchor = dt(2026, 8, 1, 12, 0)

    assert choose_scheduled_test(
        now=dt(2026, 9, 13, 2, 0),
        quick_schedule=quick,
        quick_anchor=anchor,
        deep_schedule=TestSchedule(interval_days=0, preferred_time="13:00"),
        deep_anchor=anchor,
        safe_to_test=True,
    ) is None

    assert choose_scheduled_test(
        now=dt(2026, 9, 13, 12, 15),
        quick_schedule=quick,
        quick_anchor=anchor,
        deep_schedule=TestSchedule(interval_days=0, preferred_time="13:00"),
        deep_anchor=anchor,
        safe_to_test=True,
    ) == "quick"


def test_preferred_time_window_is_one_hour_not_the_rest_of_the_day():
    quick = TestSchedule(interval_days=30, preferred_time="12:00")
    anchor = dt(2026, 8, 1, 12, 0)

    assert choose_scheduled_test(
        now=dt(2026, 9, 13, 12, 59),
        quick_schedule=quick,
        quick_anchor=anchor,
        deep_schedule=TestSchedule(interval_days=0, preferred_time="13:00"),
        deep_anchor=anchor,
        safe_to_test=True,
    ) == "quick"

    assert choose_scheduled_test(
        now=dt(2026, 9, 13, 13, 0),
        quick_schedule=quick,
        quick_anchor=anchor,
        deep_schedule=TestSchedule(interval_days=0, preferred_time="13:00"),
        deep_anchor=anchor,
        safe_to_test=True,
    ) is None


def test_deep_wins_when_quick_and_deep_are_due_in_same_window():
    quick = TestSchedule(interval_days=30, preferred_time="12:00")
    deep = TestSchedule(interval_days=180, preferred_time="12:30")
    anchor = dt(2026, 1, 1, 12, 0)

    assert choose_scheduled_test(
        now=dt(2026, 9, 13, 12, 30),
        quick_schedule=quick,
        quick_anchor=anchor,
        deep_schedule=deep,
        deep_anchor=anchor,
        safe_to_test=True,
    ) == "deep"


def test_safety_gate_rejection_keeps_test_due_for_later_window():
    quick = TestSchedule(interval_days=30, preferred_time="12:00")
    anchor = dt(2026, 8, 1, 12, 0)

    assert choose_scheduled_test(
        now=dt(2026, 9, 13, 12, 10),
        quick_schedule=quick,
        quick_anchor=anchor,
        deep_schedule=TestSchedule(interval_days=0, preferred_time="13:00"),
        deep_anchor=anchor,
        safe_to_test=False,
    ) is None

    # The pure scheduler never mutates the anchor when the gate rejects a run.
    assert next_scheduled_test(quick, anchor) == dt(2026, 8, 31, 12, 0)
    assert choose_scheduled_test(
        now=dt(2026, 9, 14, 12, 10),
        quick_schedule=quick,
        quick_anchor=anchor,
        deep_schedule=TestSchedule(interval_days=0, preferred_time="13:00"),
        deep_anchor=anchor,
        safe_to_test=True,
    ) == "quick"
