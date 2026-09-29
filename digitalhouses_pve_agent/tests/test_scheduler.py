import pytest

from app.scheduler import Scheduler


def test_task_becomes_due_and_reschedules_from_run_time():
    scheduler = Scheduler()
    scheduler.add("fast", interval_seconds=10.0, now=100.0, run_immediately=True)

    assert scheduler.due(100.0) == ("fast",)

    scheduler.mark_run("fast", now=100.0)
    assert scheduler.due(109.9) == ()
    assert scheduler.due(110.0) == ("fast",)


def test_request_run_makes_task_due_without_changing_interval():
    scheduler = Scheduler()
    scheduler.add("smart", interval_seconds=3600.0, now=100.0)

    scheduler.request_run("smart", now=160.0)

    assert scheduler.interval("smart") == 3600.0
    assert scheduler.due(159.9) == ()
    assert scheduler.due(160.0) == ("smart",)


def test_interval_can_be_changed_safely():
    scheduler = Scheduler()
    scheduler.add("disk", interval_seconds=30.0, now=0.0, run_immediately=False)
    scheduler.set_interval("disk", 60.0, now=5.0)

    assert scheduler.due(64.9) == ()
    assert scheduler.due(65.0) == ("disk",)


@pytest.mark.parametrize("interval", [0, -1])
def test_invalid_interval_is_rejected(interval):
    scheduler = Scheduler()
    with pytest.raises(ValueError):
        scheduler.add("bad", interval_seconds=interval, now=0.0)
