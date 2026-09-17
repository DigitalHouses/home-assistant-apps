from app.ups_status_events import UpsStatusEventTracker


def _observe(
    tracker,
    *,
    status,
    raw,
    observed_at="2026-09-17T12:00:00+05:00",
):
    return tracker.observe(
        current_status=status,
        current_raw_status=raw,
        observed_at=observed_at,
    )


def test_first_observation_establishes_baseline_without_event():
    tracker = UpsStatusEventTracker()

    assert _observe(tracker, status=("online",), raw=("OL",)) is None
    assert tracker.previous_status == ("online",)
    assert tracker.previous_raw_status == ("OL",)


def test_ol_to_ob_emits_previous_and_current_machine_state():
    tracker = UpsStatusEventTracker()
    _observe(tracker, status=("online",), raw=("OL",))

    event = _observe(
        tracker,
        status=("on_battery",),
        raw=("OB", "DISCHRG"),
        observed_at="2026-09-17T12:00:10+05:00",
    )

    assert event is not None
    key, payload = event
    assert key
    assert payload == {
        "schema_version": 2,
        "event_type": "ups_status_changed",
        "observed_at": "2026-09-17T12:00:10+05:00",
        "previous_status": ["online"],
        "current_status": ["on_battery"],
        "previous_raw_status": ["OL"],
        "current_raw_status": ["OB", "DISCHRG"],
    }


def test_ob_to_ol_emits_restore_transition():
    tracker = UpsStatusEventTracker()
    _observe(tracker, status=("on_battery",), raw=("OB", "DISCHRG"))

    event = _observe(
        tracker,
        status=("online",),
        raw=("OL",),
        observed_at="2026-09-17T12:00:10+05:00",
    )

    assert event is not None
    _, payload = event
    assert payload["previous_status"] == ["on_battery"]
    assert payload["current_status"] == ["online"]
    assert payload["previous_raw_status"] == ["OB", "DISCHRG"]
    assert payload["current_raw_status"] == ["OL"]


def test_boost_enter_and_exit_are_status_transitions():
    tracker = UpsStatusEventTracker()
    _observe(tracker, status=("online",), raw=("OL",))

    entered = _observe(
        tracker,
        status=("online", "boost"),
        raw=("OL", "BOOST"),
        observed_at="2026-09-17T12:00:10+05:00",
    )
    exited = _observe(
        tracker,
        status=("online",),
        raw=("OL",),
        observed_at="2026-09-17T12:00:20+05:00",
    )

    assert entered is not None
    assert entered[1]["previous_status"] == ["online"]
    assert entered[1]["current_status"] == ["online", "boost"]
    assert exited is not None
    assert exited[1]["previous_status"] == ["online", "boost"]
    assert exited[1]["current_status"] == ["online"]


def test_unchanged_canonical_status_emits_nothing_but_refreshes_raw_baseline():
    tracker = UpsStatusEventTracker()
    _observe(tracker, status=("online",), raw=("OL", "CHRG"))

    assert _observe(
        tracker,
        status=("online",),
        raw=("OL",),
        observed_at="2026-09-17T12:00:10+05:00",
    ) is None
    assert tracker.previous_raw_status == ("OL",)

    event = _observe(
        tracker,
        status=("online", "boost"),
        raw=("OL", "BOOST"),
        observed_at="2026-09-17T12:00:20+05:00",
    )
    assert event is not None
    assert event[1]["previous_raw_status"] == ["OL"]
