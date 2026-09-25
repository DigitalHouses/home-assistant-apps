from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.line_power_statistics import (
    LinePowerState,
    LinePowerStatisticsTracker,
    line_power_state_from_snapshot,
)
from app.state_store import StateStore
from app.ups_nut import parse_upsc_output


class Clock:
    def __init__(self, value: str) -> None:
        self.value = datetime.fromisoformat(value)

    def now(self) -> datetime:
        return self.value

    def advance(self, *, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class CountingStore:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.save_count = 0

    def load(self) -> dict[str, object]:
        return dict(self.data)

    def save(self, data) -> None:
        self.data = dict(data)
        self.save_count += 1


def test_first_online_observation_starts_partial_month_without_backfill(tmp_path):
    clock = Clock("2026-09-17T03:00:00+05:00")
    tracker = LinePowerStatisticsTracker(
        StateStore(tmp_path / "line.json"),
        now_local=clock.now,
    )

    assert tracker.observe(LinePowerState.ONLINE) is True
    snap = tracker.snapshot()

    assert snap.month_key == "2026-09"
    assert snap.month_label_ru == "сентябрь"
    assert snap.partial_month is True
    assert snap.tracking_since == "2026-09-17T03:00:00+05:00"
    assert snap.online_seconds == 0
    assert snap.offline_seconds == 0
    assert snap.unknown_seconds == 0
    assert snap.outages_month == 0
    assert snap.availability_percent is None


def test_online_to_offline_accounts_time_and_starts_one_outage(tmp_path):
    clock = Clock("2026-09-17T03:00:00+05:00")
    tracker = LinePowerStatisticsTracker(
        StateStore(tmp_path / "line.json"),
        now_local=clock.now,
    )
    tracker.observe(LinePowerState.ONLINE)
    clock.advance(seconds=120)

    assert tracker.observe(LinePowerState.OFFLINE) is True
    snap = tracker.snapshot()

    assert snap.online_seconds == 120
    assert snap.offline_seconds == 0
    assert snap.outages_month == 1
    assert snap.current_outage_started == "2026-09-17T03:02:00+05:00"
    assert snap.last_failure == "2026-09-17T03:02:00+05:00"
    assert snap.availability_percent == 100.0


def test_unknown_is_excluded_from_availability_denominator(tmp_path):
    clock = Clock("2026-09-17T03:00:00+05:00")
    tracker = LinePowerStatisticsTracker(
        StateStore(tmp_path / "line.json"),
        now_local=clock.now,
    )
    tracker.observe(LinePowerState.ONLINE)
    clock.advance(seconds=100)
    tracker.observe(LinePowerState.UNKNOWN)
    clock.advance(seconds=50)
    tracker.observe(LinePowerState.OFFLINE)
    clock.advance(seconds=100)

    snap = tracker.snapshot()

    assert snap.online_seconds == 100
    assert snap.unknown_seconds == 50
    assert snap.offline_seconds == 100
    assert snap.availability_percent == 50.0
    assert snap.outages_month == 1


def test_offline_to_online_closes_outage_with_real_duration(tmp_path):
    clock = Clock("2026-09-17T03:00:00+05:00")
    tracker = LinePowerStatisticsTracker(
        StateStore(tmp_path / "line.json"),
        now_local=clock.now,
    )
    tracker.observe(LinePowerState.ONLINE)
    clock.advance(seconds=30)
    tracker.observe(LinePowerState.OFFLINE)
    clock.advance(seconds=90)

    assert tracker.observe(LinePowerState.ONLINE) is True
    snap = tracker.snapshot()

    assert snap.offline_seconds == 90
    assert snap.last_outage_duration_seconds == 90
    assert snap.current_outage_started is None
    assert snap.last_restore == "2026-09-17T03:02:00+05:00"
    assert snap.estimated_restore is False
    assert snap.availability_percent == 25.0


def test_restart_from_open_outage_marks_restore_estimated(tmp_path):
    path = tmp_path / "line.json"
    clock = Clock("2026-09-17T03:00:00+05:00")
    tracker = LinePowerStatisticsTracker(StateStore(path), now_local=clock.now)
    tracker.observe(LinePowerState.OFFLINE)
    clock.advance(seconds=120)

    restarted = LinePowerStatisticsTracker(StateStore(path), now_local=clock.now)
    assert restarted.observe(LinePowerState.ONLINE) is True
    snap = restarted.snapshot()

    assert snap.offline_seconds == 120
    assert snap.last_outage_duration_seconds == 120
    assert snap.last_restore == "2026-09-17T03:02:00+05:00"
    assert snap.estimated_restore is True


def test_cross_month_outage_carries_duration_without_new_outage_count(tmp_path):
    clock = Clock("2026-09-30T23:59:50+05:00")
    tracker = LinePowerStatisticsTracker(
        StateStore(tmp_path / "line.json"),
        now_local=clock.now,
    )
    tracker.observe(LinePowerState.OFFLINE)
    assert tracker.snapshot().outages_month == 1

    clock.advance(seconds=20)
    snap = tracker.snapshot()

    assert snap.month_key == "2026-10"
    assert snap.month_label_ru == "октябрь"
    assert snap.partial_month is False
    assert snap.offline_seconds == 10
    assert snap.outages_month == 0
    assert snap.current_outage_started == "2026-09-30T23:59:50+05:00"


def test_snapshot_does_not_persist_on_every_poll():
    store = CountingStore()
    clock = Clock("2026-09-17T03:00:00+05:00")
    tracker = LinePowerStatisticsTracker(store, now_local=clock.now)

    tracker.observe(LinePowerState.ONLINE)
    after_initial = store.save_count
    clock.advance(seconds=10)
    tracker.snapshot()
    clock.advance(seconds=10)
    tracker.snapshot()

    assert store.save_count == after_initial


def test_classifier_uses_nut_status_not_voltage():
    online = parse_upsc_output("ups.status: OL\ninput.voltage: 70\n")
    offline = parse_upsc_output("ups.status: OB DISCHRG\ninput.voltage: 230\n")
    ambiguous = parse_upsc_output("ups.status: OL OB\ninput.voltage: 230\n")

    assert line_power_state_from_snapshot(online, nut_available=True) is LinePowerState.ONLINE
    assert line_power_state_from_snapshot(offline, nut_available=True) is LinePowerState.OFFLINE
    assert line_power_state_from_snapshot(ambiguous, nut_available=True) is LinePowerState.UNKNOWN
    assert line_power_state_from_snapshot(online, nut_available=False) is LinePowerState.UNKNOWN


def test_naive_local_clock_is_rejected(tmp_path):
    tracker = LinePowerStatisticsTracker(
        StateStore(tmp_path / "line.json"),
        now_local=lambda: datetime(2026, 9, 17, 3, 0, 0),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        tracker.observe(LinePowerState.ONLINE)
