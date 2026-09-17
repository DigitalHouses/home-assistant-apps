from app.state_store import StateStore
from app.ups_battery_events import DISCHARGE_THRESHOLDS, UpsBatteryEventTracker


def _tracker(tmp_path):
    return UpsBatteryEventTracker(StateStore(tmp_path / "ups_battery_events.json"))


def _observe(
    tracker,
    *,
    on_battery=True,
    charge,
    observed_at="2026-09-17T12:00:00+05:00",
):
    return tracker.observe_discharge(
        on_battery=on_battery,
        charge_percent=charge,
        observed_at=observed_at,
    )


def _thresholds(events):
    if not events:
        return []
    assert len(events) == 1
    return events[0][1]["crossed_thresholds"]


def test_discharge_thresholds_are_canonical():
    assert DISCHARGE_THRESHOLDS == (90, 80, 70, 60, 50, 40, 30, 20, 10)


def test_crossing_single_threshold_emits_once(tmp_path):
    tracker = _tracker(tmp_path)
    assert _observe(tracker, charge=94) == ()

    events = _observe(
        tracker,
        charge=87,
        observed_at="2026-09-17T12:00:10+05:00",
    )

    assert _thresholds(events) == [90]
    key, payload = events[0]
    assert key
    assert payload == {
        "schema_version": 2,
        "event_type": "battery_discharge_level_crossed",
        "observed_at": "2026-09-17T12:00:10+05:00",
        "previous_charge_percent": 94,
        "current_charge_percent": 87,
        "crossed_thresholds": [90],
    }


def test_large_sample_jump_emits_one_event_with_all_crossed_thresholds(tmp_path):
    tracker = _tracker(tmp_path)
    assert _observe(tracker, charge=94) == ()

    events = _observe(tracker, charge=67)

    assert _thresholds(events) == [90, 80, 70]


def test_exact_threshold_is_a_crossing(tmp_path):
    tracker = _tracker(tmp_path)
    assert _observe(tracker, charge=91) == ()

    assert _thresholds(_observe(tracker, charge=90)) == [90]


def test_emitted_threshold_is_not_duplicated_in_same_session(tmp_path):
    tracker = _tracker(tmp_path)
    _observe(tracker, charge=94)
    assert _thresholds(_observe(tracker, charge=89)) == [90]

    assert _observe(tracker, charge=87) == ()


def test_upward_estimator_move_does_not_emit_discharge_milestone(tmp_path):
    tracker = _tracker(tmp_path)
    _observe(tracker, charge=87)

    assert _observe(tracker, charge=92) == ()


def test_line_power_context_does_not_emit_discharge_milestones(tmp_path):
    tracker = _tracker(tmp_path)
    assert _observe(tracker, on_battery=False, charge=94) == ()
    assert _observe(tracker, on_battery=False, charge=87) == ()


def test_restart_preserves_emitted_thresholds_and_previous_charge(tmp_path):
    store = StateStore(tmp_path / "ups_battery_events.json")
    tracker = UpsBatteryEventTracker(store)
    _observe(tracker, charge=94)
    assert _thresholds(_observe(tracker, charge=87)) == [90]

    reloaded = UpsBatteryEventTracker(store)
    events = _observe(
        reloaded,
        charge=79,
        observed_at="2026-09-17T12:00:20+05:00",
    )

    assert _thresholds(events) == [80]
    assert events[0][1]["previous_charge_percent"] == 87
    assert events[0][1]["current_charge_percent"] == 79


def test_startup_already_low_establishes_baseline_without_inventing_crossings(tmp_path):
    tracker = _tracker(tmp_path)

    assert _observe(tracker, charge=67) == ()
    assert _observe(tracker, charge=66) == ()


def test_new_discharge_session_resets_emitted_thresholds(tmp_path):
    tracker = _tracker(tmp_path)
    _observe(tracker, charge=94)
    assert _thresholds(_observe(tracker, charge=87)) == [90]

    assert _observe(tracker, on_battery=False, charge=92) == ()
    assert _observe(tracker, on_battery=True, charge=94) == ()
    assert _thresholds(_observe(tracker, charge=88)) == [90]


def test_missing_charge_does_not_create_crossing_evidence(tmp_path):
    tracker = _tracker(tmp_path)
    assert _observe(tracker, charge=None) == ()
    assert _observe(tracker, charge=87) == ()
