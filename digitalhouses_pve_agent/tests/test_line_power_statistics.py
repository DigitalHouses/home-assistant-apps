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


def test_monthly_outage_rows_include_active_and_completed_events(tmp_path):
    clock = Clock("2026-10-01T12:00:00+05:00")
    path = tmp_path / "line.json"
    tracker = LinePowerStatisticsTracker(StateStore(path), now_local=clock.now)
    tracker.observe(LinePowerState.ONLINE)
    clock.advance(seconds=10)
    tracker.observe(LinePowerState.OFFLINE)
    clock.advance(seconds=75)
    live = tracker.snapshot()
    assert live.outages_month == 1
    assert live.outages[0]["to"] is None
    assert live.outages[0]["duration_seconds"] == 75

    clock.advance(seconds=15)
    tracker.observe(LinePowerState.ONLINE)
    done = tracker.snapshot()
    assert done.outages == [{
        "from": "2026-10-01T12:00:10+05:00",
        "to": "2026-10-01T12:01:40+05:00",
        "duration_seconds": 90,
        "estimated": False,
    }]
    assert done.offline_seconds == 90
    restarted = LinePowerStatisticsTracker(StateStore(path), now_local=clock.now)
    assert restarted.snapshot().outages == done.outages


def test_unavailable_nut_does_not_make_false_outage_or_restore(tmp_path):
    clock = Clock("2026-10-02T12:00:00+05:00")
    tracker = LinePowerStatisticsTracker(StateStore(tmp_path / "line.json"), now_local=clock.now)
    tracker.observe(LinePowerState.ONLINE)
    clock.advance(seconds=30)
    tracker.observe(LinePowerState.UNKNOWN)
    assert tracker.snapshot().outages == []
    clock.advance(seconds=10)
    tracker.observe(LinePowerState.ONLINE)
    assert tracker.snapshot().outages_month == 0

    clock.advance(seconds=10)
    tracker.observe(LinePowerState.OFFLINE)
    clock.advance(seconds=10)
    tracker.observe(LinePowerState.UNKNOWN)
    clock.advance(seconds=10)
    tracker.observe(LinePowerState.OFFLINE)
    assert tracker.snapshot().outages_month == 1
    clock.advance(seconds=10)
    tracker.observe(LinePowerState.ONLINE)
    rows = tracker.snapshot().outages
    assert len(rows) == 1
    assert rows[0]["estimated"] is True


def test_upgrade_keeps_existing_counters_without_inventing_past_incidents(tmp_path):
    path = tmp_path / "line.json"
    clock = Clock("2026-10-03T12:00:00+05:00")
    original = LinePowerStatisticsTracker(StateStore(path), now_local=clock.now)
    original.observe(LinePowerState.ONLINE)
    clock.advance(seconds=10)
    original.observe(LinePowerState.OFFLINE)
    clock.advance(seconds=5)
    original.observe(LinePowerState.ONLINE)
    from app.state_store import StateStore as Store
    persisted = Store(path).load()
    persisted.pop("outage_history")
    persisted.pop("outage_history_since")
    persisted.pop("outage_uncertain")
    Store(path).save(persisted)

    migrated = LinePowerStatisticsTracker(Store(path), now_local=clock.now)
    current = migrated.snapshot()
    assert current.outages_month == 1
    assert current.outages == []
    assert current.history_partial_month is True
    assert current.history_since == clock.now().isoformat()


def test_new_month_resets_rows_but_keeps_ongoing_outage(tmp_path):
    clock = Clock("2026-09-30T23:59:50+05:00")
    tracker = LinePowerStatisticsTracker(StateStore(tmp_path / "line.json"), now_local=clock.now)
    tracker.observe(LinePowerState.OFFLINE)
    clock.advance(seconds=20)
    current = tracker.snapshot()
    assert current.outages_month == 0
    assert current.offline_seconds == 10
    assert len(current.outages) == 1
    assert current.outages[0]["from"] == "2026-09-30T23:59:50+05:00"
    assert current.outages[0]["to"] is None
    clock.advance(seconds=10)
    tracker.observe(LinePowerState.ONLINE)
    assert len(tracker.snapshot().outages) == 1
    assert tracker.snapshot().outages[0]["duration_seconds"] == 30


def test_mqtt_recent_rows_bounded_but_local_monthly_incidents_complete(tmp_path):
    clock = Clock("2026-10-04T00:00:00+05:00")
    store = StateStore(tmp_path / "line.json")
    tracker = LinePowerStatisticsTracker(store, now_local=clock.now)
    tracker.observe(LinePowerState.ONLINE)
    for _ in range(15):
        clock.advance(seconds=5)
        tracker.observe(LinePowerState.OFFLINE)
        clock.advance(seconds=5)
        tracker.observe(LinePowerState.ONLINE)
    snap = tracker.snapshot()
    assert snap.outages_month == 15
    assert len(snap.outages) == 10
    assert snap.omitted_count == 5
    assert len(store.load()["outage_history"]) == 15


def test_corrupt_detailed_history_fails_closed(tmp_path):
    from app.state_store import StateStoreError
    path = tmp_path / "line.json"
    clock = Clock("2026-10-04T00:00:00+05:00")
    tracker = LinePowerStatisticsTracker(StateStore(path), now_local=clock.now)
    tracker.observe(LinePowerState.ONLINE)
    data = StateStore(path).load()
    data["outage_history"] = [{"from": "broken"}]
    StateStore(path).save(data)
    with pytest.raises(StateStoreError):
        LinePowerStatisticsTracker(StateStore(path), now_local=clock.now)


def test_quality_boost_trim_bypass_overload_are_independent_from_outages(tmp_path):
    clock = Clock("2026-10-04T02:00:00+05:00")
    tracker = LinePowerStatisticsTracker(StateStore(tmp_path / "line.json"), now_local=clock.now)
    tracker.observe(LinePowerState.ONLINE, quality_statuses=("online",))
    clock.advance(seconds=10)
    tracker.observe(LinePowerState.ONLINE, quality_statuses=("online", "boost"))
    clock.advance(seconds=20)
    tracker.observe(LinePowerState.ONLINE, quality_statuses=("online", "trim", "overload"))
    clock.advance(seconds=5)
    tracker.observe(LinePowerState.ONLINE, quality_statuses=("online", "bypass"))
    clock.advance(seconds=15)
    tracker.observe(LinePowerState.ONLINE, quality_statuses=("online",))

    snap = tracker.snapshot()
    assert snap.outages_month == 0
    assert snap.offline_seconds == 0
    assert snap.outages == []
    assert [(r["event"], r["duration_seconds"]) for r in snap.events] == [
        ("boost", 20), ("overload", 5), ("trim", 5), ("bypass", 15)
    ]
    assert all(r["estimated"] is False for r in snap.events)
    assert snap.quality_revision == 4


def test_overlapping_outage_and_quality_intervals_in_one_table(tmp_path):
    clock = Clock("2026-10-04T02:00:00+05:00")
    tracker = LinePowerStatisticsTracker(StateStore(tmp_path / "line.json"), now_local=clock.now)
    tracker.observe(LinePowerState.ONLINE, quality_statuses=("online",))
    clock.advance(seconds=10)
    tracker.observe(LinePowerState.OFFLINE, quality_statuses=("on_battery", "overload"))
    clock.advance(seconds=40)
    tracker.observe(LinePowerState.ONLINE, quality_statuses=("online",))
    snap = tracker.snapshot()
    assert snap.outages_month == 1
    assert snap.offline_seconds == 40
    assert len(snap.outages) == 1
    assert {r["event"] for r in snap.events} == {"outage", "overload"}
    assert all(r["duration_seconds"] == 40 for r in snap.events)


def test_quality_active_persists_restart_and_unknown_marks_estimated(tmp_path):
    path = tmp_path / "line.json"
    clock = Clock("2026-10-04T02:00:00+05:00")
    tracker = LinePowerStatisticsTracker(StateStore(path), now_local=clock.now)
    tracker.observe(LinePowerState.ONLINE, quality_statuses=("online",))
    clock.advance(seconds=10)
    tracker.observe(LinePowerState.ONLINE, quality_statuses=("online", "boost"))
    assert tracker.snapshot().events[0]["estimated"] is False

    clock.advance(seconds=10)
    restarted = LinePowerStatisticsTracker(StateStore(path), now_local=clock.now)
    restarted.observe(LinePowerState.ONLINE, quality_statuses=("online", "boost"))
    assert restarted.snapshot().events[0]["estimated"] is True
    clock.advance(seconds=10)
    restarted.observe(LinePowerState.UNKNOWN)
    assert restarted.snapshot().events[0]["to"] is None
    clock.advance(seconds=10)
    restarted.observe(LinePowerState.ONLINE, quality_statuses=("online",))
    result = restarted.snapshot().events[0]
    assert result["event"] == "boost"
    assert result["duration_seconds"] == 30
    assert result["estimated"] is True
    assert restarted.snapshot().outages_month == 0


def test_initial_unknown_quality_status_start_is_approximate(tmp_path):
    clock = Clock("2026-10-04T02:00:00+05:00")
    tracker = LinePowerStatisticsTracker(StateStore(tmp_path / "line.json"), now_local=clock.now)
    tracker.observe(LinePowerState.ONLINE, quality_statuses=("online", "trim"))
    assert tracker.snapshot().events[0]["estimated"] is True
    assert tracker.snapshot().events[0]["from"] == clock.now().isoformat()


def test_quality_events_survive_month_roll_without_recount(tmp_path):
    clock = Clock("2026-09-30T23:59:50+05:00")
    tracker = LinePowerStatisticsTracker(StateStore(tmp_path / "line.json"), now_local=clock.now)
    tracker.observe(LinePowerState.ONLINE, quality_statuses=("online",))
    clock.advance(seconds=5)
    tracker.observe(LinePowerState.ONLINE, quality_statuses=("online", "boost"))
    clock.advance(seconds=10)
    monthly = tracker.snapshot()
    assert monthly.month_key == "2026-10"
    assert monthly.outages_month == 0
    assert monthly.events[0]["from"] == "2026-09-30T23:59:55+05:00"
    assert monthly.quality_history_partial_month is False
    clock.advance(seconds=5)
    tracker.observe(LinePowerState.ONLINE, quality_statuses=("online",))
    assert tracker.snapshot().events[0]["duration_seconds"] == 15


def test_legacy_v054_outage_history_is_not_changed_by_quality_upgrade(tmp_path):
    path = tmp_path / "line.json"
    store = StateStore(path)
    clock = Clock("2026-10-04T02:00:00+05:00")
    tracker = LinePowerStatisticsTracker(store, now_local=clock.now)
    tracker.observe(LinePowerState.ONLINE)
    clock.advance(seconds=5)
    tracker.observe(LinePowerState.OFFLINE)
    clock.advance(seconds=20)
    tracker.observe(LinePowerState.ONLINE)
    saved = store.load()
    for key in ("quality_history", "quality_active", "quality_history_since", "quality_revision"):
        saved.pop(key)
    store.save(saved)
    upgraded = LinePowerStatisticsTracker(store, now_local=clock.now)
    snap = upgraded.snapshot()
    assert snap.outages_month == 1
    assert snap.outages[0]["duration_seconds"] == 20
    assert len(snap.events) == 1
    assert snap.events[0]["event"] == "outage"
    assert snap.quality_history_since == clock.now().isoformat()


def test_recent_power_events_are_bounded_without_dropping_month_data(tmp_path):
    clock = Clock("2026-10-04T02:00:00+05:00")
    store = StateStore(tmp_path / "line.json")
    tracker = LinePowerStatisticsTracker(store, now_local=clock.now)
    tracker.observe(LinePowerState.ONLINE, quality_statuses=("online",))
    for _ in range(14):
        clock.advance(seconds=5)
        tracker.observe(LinePowerState.ONLINE, quality_statuses=("online", "trim"))
        clock.advance(seconds=5)
        tracker.observe(LinePowerState.ONLINE, quality_statuses=("online",))
    snap = tracker.snapshot()
    assert snap.outages_month == 0
    assert len(snap.events) == 10
    assert snap.events_omitted_count == 4
    assert len(store.load()["quality_history"]) == 14


def test_corrupt_quality_history_rejected(tmp_path):
    from app.state_store import StateStoreError
    clock = Clock("2026-10-04T02:00:00+05:00")
    store = StateStore(tmp_path / "line.json")
    tracker = LinePowerStatisticsTracker(store, now_local=clock.now)
    tracker.observe(LinePowerState.ONLINE)
    raw = store.load()
    raw["quality_history"] = [{"event": "boost", "from": "broken"}]
    store.save(raw)
    with pytest.raises(StateStoreError):
        LinePowerStatisticsTracker(store, now_local=clock.now)
