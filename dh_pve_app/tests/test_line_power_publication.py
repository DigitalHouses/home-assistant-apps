from app.presentation_ups import UpsPresentationRouter


def _stats(state: str, *, online: int = 0, offline: int = 0) -> dict[str, object]:
    known = online + offline
    availability = round((online / known) * 100.0, 2) if known else None
    return {
        "state": state,
        "month_key": "2026-09",
        "month_label_ru": "сентябрь",
        "tracking_since": "2026-09-17T03:00:00+05:00",
        "partial_month": True,
        "state_since": "2026-09-17T03:00:00+05:00",
        "online_seconds": online,
        "offline_seconds": offline,
        "unknown_seconds": 0,
        "outages_month": 1 if offline else 0,
        "availability_percent": availability,
        "current_outage_started": None,
        "last_failure": None,
        "last_restore": None,
        "last_outage_duration_seconds": None,
        "estimated_restore": False,
    }


def _payload(stats: dict[str, object]) -> dict[str, object]:
    return {
        "available": True,
        "load_percent": 5.0,
        "on_battery": stats["state"] == "offline",
        "low_battery": False,
        "overload": False,
        "bypass": False,
        "line_power_statistics": stats,
    }


def _stats_publications(router, payload, *, now: float, force: bool = False, manual: bool = False):
    return [
        item
        for item in router.route(payload, now=now, force=force, manual=manual)
        if item.group == "line_power_statistics"
    ]


def test_online_statistics_publish_every_600_seconds():
    router = UpsPresentationRouter(source_interval_seconds=10.0)

    first = _stats_publications(router, _payload(_stats("online")), now=0.0, force=True)
    before = _stats_publications(
        router,
        _payload(_stats("online", online=599)),
        now=599.0,
    )
    due = _stats_publications(
        router,
        _payload(_stats("online", online=600)),
        now=600.0,
    )

    assert len(first) == 1
    assert before == []
    assert len(due) == 1
    assert due[0].reason == "interval"


def test_offline_statistics_publish_every_10_seconds():
    router = UpsPresentationRouter(source_interval_seconds=10.0)

    first = _stats_publications(router, _payload(_stats("offline")), now=0.0, force=True)
    before = _stats_publications(
        router,
        _payload(_stats("offline", offline=9)),
        now=9.0,
    )
    due = _stats_publications(
        router,
        _payload(_stats("offline", offline=10)),
        now=10.0,
    )

    assert len(first) == 1
    assert before == []
    assert len(due) == 1
    assert due[0].reason == "interval"


def test_line_power_state_transition_publishes_immediately():
    router = UpsPresentationRouter(source_interval_seconds=10.0)
    _stats_publications(router, _payload(_stats("online")), now=0.0, force=True)

    offline = _stats_publications(
        router,
        _payload(_stats("offline", online=1)),
        now=1.0,
    )
    unknown = _stats_publications(
        router,
        _payload(_stats("unknown", online=1)),
        now=2.0,
    )

    assert len(offline) == 1
    assert offline[0].reason == "state_change"
    assert len(unknown) == 1
    assert unknown[0].reason == "state_change"


def test_unknown_does_not_use_offline_10_second_profile():
    router = UpsPresentationRouter(source_interval_seconds=10.0)
    _stats_publications(router, _payload(_stats("unknown")), now=0.0, force=True)

    assert _stats_publications(router, _payload(_stats("unknown")), now=10.0) == []
    assert _stats_publications(router, _payload(_stats("unknown")), now=599.0) == []
    assert len(_stats_publications(router, _payload(_stats("unknown")), now=600.0)) == 1


def test_manual_refresh_forces_statistics_publication():
    router = UpsPresentationRouter(source_interval_seconds=10.0)
    _stats_publications(router, _payload(_stats("online")), now=0.0, force=True)

    manual = _stats_publications(
        router,
        _payload(_stats("online", online=1)),
        now=1.0,
        manual=True,
    )

    assert len(manual) == 1
    assert manual[0].reason == "manual_refresh"
