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


def _observe_charge(
    tracker,
    *,
    charger_status,
    charge,
    line_power=True,
    raw=("OL",),
    observed_at="2026-09-17T13:00:00+05:00",
):
    return tracker.observe_charge_cycle(
        charger_status=charger_status,
        charge_percent=charge,
        line_power=line_power,
        raw_status_tokens=raw,
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


def test_direct_charging_to_floating_emits_completed_cycle(tmp_path):
    tracker = _tracker(tmp_path)
    assert _observe_charge(
        tracker,
        charger_status="charging",
        charge=97,
        raw=("OL", "CHRG"),
    ) == ()

    events = _observe_charge(
        tracker,
        charger_status="floating",
        charge=98,
        raw=("OL", "CHRG"),
        observed_at="2026-09-17T13:00:10+05:00",
    )

    assert len(events) == 1
    key, payload = events[0]
    assert key
    assert payload == {
        "schema_version": 2,
        "event_type": "battery_fully_charged",
        "observed_at": "2026-09-17T13:00:10+05:00",
        "previous_charge_percent": 97,
        "current_charge_percent": 98,
        "previous_charger_status": "charging",
        "current_charger_status": "floating",
        "detection_source": "charger_status",
    }


def test_direct_charging_to_resting_emits_once_without_requiring_100_percent(tmp_path):
    tracker = _tracker(tmp_path)
    _observe_charge(tracker, charger_status="charging", charge=97, raw=("OL", "CHRG"))

    events = _observe_charge(
        tracker,
        charger_status="resting",
        charge=98,
        raw=("OL",),
        observed_at="2026-09-17T13:00:10+05:00",
    )

    assert len(events) == 1
    assert events[0][1]["current_charge_percent"] == 98
    assert events[0][1]["detection_source"] == "charger_status"


def test_floating_to_resting_does_not_duplicate_same_charge_cycle(tmp_path):
    tracker = _tracker(tmp_path)
    _observe_charge(tracker, charger_status="charging", charge=97, raw=("OL", "CHRG"))
    first = _observe_charge(tracker, charger_status="floating", charge=98, raw=("OL",))
    second = _observe_charge(tracker, charger_status="resting", charge=98, raw=("OL",))

    assert len(first) == 1
    assert second == ()


def test_startup_already_completed_does_not_invent_fully_charged_event(tmp_path):
    for status in ("resting", "floating", "idle"):
        tracker = UpsBatteryEventTracker(
            StateStore(tmp_path / f"ups_battery_events_{status}.json")
        )
        assert _observe_charge(
            tracker,
            charger_status=status,
            charge=100,
            raw=("OL",),
        ) == ()


def test_legacy_fallback_requires_two_stable_idle_samples(tmp_path):
    tracker = _tracker(tmp_path)
    assert _observe_charge(
        tracker,
        charger_status="charging",
        charge=96,
        raw=("OL", "CHRG"),
    ) == ()

    first_idle = _observe_charge(
        tracker,
        charger_status="idle",
        charge=98,
        raw=("OL",),
        observed_at="2026-09-17T13:00:10+05:00",
    )
    second_idle = _observe_charge(
        tracker,
        charger_status="idle",
        charge=98,
        raw=("OL",),
        observed_at="2026-09-17T13:00:20+05:00",
    )

    assert first_idle == ()
    assert len(second_idle) == 1
    payload = second_idle[0][1]
    assert payload["event_type"] == "battery_fully_charged"
    assert payload["previous_charge_percent"] == 96
    assert payload["current_charge_percent"] == 98
    assert payload["previous_charger_status"] == "charging"
    assert payload["current_charger_status"] == "idle"
    assert payload["detection_source"] == "legacy_status_fallback"


def test_legacy_one_sample_token_flap_then_charging_emits_nothing(tmp_path):
    tracker = _tracker(tmp_path)
    _observe_charge(tracker, charger_status="charging", charge=96, raw=("OL", "CHRG"))
    assert _observe_charge(tracker, charger_status="idle", charge=98, raw=("OL",)) == ()
    assert _observe_charge(
        tracker,
        charger_status="charging",
        charge=98,
        raw=("OL", "CHRG"),
    ) == ()


def test_direct_completion_wins_over_conflicting_legacy_charging_token(tmp_path):
    tracker = _tracker(tmp_path)
    _observe_charge(tracker, charger_status="charging", charge=97, raw=("OL", "CHRG"))

    events = _observe_charge(
        tracker,
        charger_status="floating",
        charge=98,
        raw=("OL", "CHRG"),
        observed_at="2026-09-17T13:00:10+05:00",
    )

    assert len(events) == 1
    assert events[0][1]["current_charger_status"] == "floating"
    assert events[0][1]["detection_source"] == "charger_status"


def test_completed_cycle_latch_survives_restart(tmp_path):
    store = StateStore(tmp_path / "ups_battery_events.json")
    tracker = UpsBatteryEventTracker(store)
    _observe_charge(tracker, charger_status="charging", charge=97, raw=("OL", "CHRG"))
    assert len(_observe_charge(tracker, charger_status="floating", charge=98, raw=("OL",))) == 1

    reloaded = UpsBatteryEventTracker(store)
    assert _observe_charge(reloaded, charger_status="resting", charge=98, raw=("OL",)) == ()


def test_new_charging_cycle_rearms_fully_charged_event(tmp_path):
    tracker = _tracker(tmp_path)
    _observe_charge(tracker, charger_status="charging", charge=97, raw=("OL", "CHRG"))
    assert len(_observe_charge(tracker, charger_status="floating", charge=98, raw=("OL",))) == 1

    assert _observe_charge(tracker, charger_status="charging", charge=95, raw=("OL", "CHRG")) == ()
    second = _observe_charge(tracker, charger_status="resting", charge=98, raw=("OL",))
    assert len(second) == 1
