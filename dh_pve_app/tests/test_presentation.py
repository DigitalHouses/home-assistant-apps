from app.presentation import AdaptiveGroup, ProfileWindows, PublicationProfile


def test_default_profile_windows_match_recorder_policy():
    windows = ProfileWindows()

    assert windows.seconds(PublicationProfile.CRITICAL) == 30.0
    assert windows.seconds(PublicationProfile.HIGH) == 60.0
    assert windows.seconds(PublicationProfile.NORMAL) == 600.0
    assert windows.seconds(PublicationProfile.QUIET) == 3600.0


def test_critical_profile_publishes_one_average_per_30_seconds():
    group = AdaptiveGroup(initial_profile=PublicationProfile.CRITICAL)

    startup = group.observe(now=0.0, continuous={"cpu": 10.0})
    assert startup.publish is True
    assert startup.reason == "startup"
    assert startup.values["cpu"] == 10.0

    assert group.observe(now=10.0, continuous={"cpu": 20.0}).publish is False
    assert group.observe(now=20.0, continuous={"cpu": 40.0}).publish is False

    decision = group.observe(now=30.0, continuous={"cpu": 50.0})
    assert decision.publish is True
    assert decision.reason == "average_window_complete"
    assert decision.values["cpu"] == 36.67


def test_profile_transition_publishes_current_bucket_average_not_raw_sample():
    group = AdaptiveGroup()

    group.observe(now=0.0, continuous={"cpu": 10.0})
    group.observe(now=10.0, continuous={"cpu": 20.0})
    decision = group.observe(
        now=20.0,
        continuous={"cpu": 40.0},
        requested_profile=PublicationProfile.HIGH,
    )

    assert decision.publish is True
    assert decision.profile is PublicationProfile.HIGH
    assert decision.profile_changed is True
    assert decision.reason == "profile_transition"
    assert decision.values["cpu"] == 30.0


def test_discrete_change_publishes_immediately_without_waiting_for_window():
    group = AdaptiveGroup()

    group.observe(
        now=0.0,
        continuous={"temperature": 60.0},
        discrete={"throttling": False},
    )
    decision = group.observe(
        now=5.0,
        continuous={"temperature": 65.0},
        discrete={"throttling": True},
    )

    assert decision.publish is True
    assert decision.reason == "change"
    assert decision.values["throttling"] is True


def test_unchanged_completed_average_is_suppressed_but_bucket_advances():
    group = AdaptiveGroup(initial_profile=PublicationProfile.CRITICAL)

    group.observe(now=0.0, continuous={"cpu": 10.0})
    group.observe(now=10.0, continuous={"cpu": 10.0})
    group.observe(now=20.0, continuous={"cpu": 10.0})
    unchanged = group.observe(now=30.0, continuous={"cpu": 10.0})
    assert unchanged.publish is False

    group.observe(now=40.0, continuous={"cpu": 20.0})
    group.observe(now=50.0, continuous={"cpu": 20.0})
    changed = group.observe(now=60.0, continuous={"cpu": 20.0})
    assert changed.publish is True
    assert changed.reason == "average_window_complete"
    assert changed.values["cpu"] == 20.0


def test_manual_refresh_publishes_current_truth_without_resetting_average_bucket():
    windows = ProfileWindows(normal=30.0)
    group = AdaptiveGroup(windows=windows)

    group.observe(now=0.0, continuous={"cpu": 0.0})
    group.observe(now=10.0, continuous={"cpu": 10.0})

    manual = group.observe(now=15.0, continuous={"cpu": 100.0}, manual=True)
    assert manual.publish is True
    assert manual.reason == "manual_refresh"
    assert manual.values["cpu"] == 100.0

    group.observe(now=20.0, continuous={"cpu": 20.0})
    regular = group.observe(now=30.0, continuous={"cpu": 30.0})
    assert regular.publish is True
    assert regular.reason == "average_window_complete"
    assert regular.values["cpu"] == 40.0


def test_publication_window_cannot_be_faster_than_source_collection_interval():
    group = AdaptiveGroup(
        initial_profile=PublicationProfile.CRITICAL,
        source_interval_seconds=60.0,
    )

    group.observe(now=0.0, continuous={"temperature": 70.0})
    assert group.observe(now=30.0, continuous={"temperature": 75.0}).publish is False

    decision = group.observe(now=60.0, continuous={"temperature": 80.0})
    assert decision.publish is True
    assert decision.reason == "average_window_complete"
    assert decision.values["temperature"] == 77.5
