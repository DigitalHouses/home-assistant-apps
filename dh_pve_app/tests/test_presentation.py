from app.presentation import AdaptiveGroup, ProfileWindows, PublicationProfile


def test_publication_profiles_are_only_normal_and_detail():
    assert {item.value for item in PublicationProfile} == {"normal", "detail"}


def test_publication_windows_match_frozen_contract():
    windows = ProfileWindows()

    assert windows.normal_seconds == 900.0
    assert windows.detail_seconds == 300.0
    assert windows.seconds(PublicationProfile.NORMAL) == 900.0
    assert windows.seconds(PublicationProfile.DETAIL) == 300.0


def test_detail_profile_publishes_one_average_per_five_minutes():
    group = AdaptiveGroup(initial_profile=PublicationProfile.DETAIL)

    startup = group.observe(now=0.0, continuous={"cpu": 10.0})
    assert startup.publish is True
    assert startup.values["cpu"] == 10.0

    assert group.observe(now=100.0, continuous={"cpu": 20.0}).publish is False
    assert group.observe(now=200.0, continuous={"cpu": 40.0}).publish is False

    decision = group.observe(now=300.0, continuous={"cpu": 60.0})
    assert decision.publish is True
    assert decision.reason == "average_window_complete"
    assert decision.values["cpu"] == 40.0


def test_normal_profile_uses_fifteen_minute_window():
    group = AdaptiveGroup(initial_profile=PublicationProfile.NORMAL)

    group.observe(now=0.0, continuous={"cpu": 10.0})
    assert group.observe(now=899.0, continuous={"cpu": 20.0}).publish is False
    decision = group.observe(now=900.0, continuous={"cpu": 30.0})

    assert decision.publish is True
    assert decision.values["cpu"] == 25.0


def test_profile_transition_publishes_current_bucket_average_not_raw_sample():
    group = AdaptiveGroup()

    group.observe(now=0.0, continuous={"cpu": 10.0})
    group.observe(now=10.0, continuous={"cpu": 20.0})
    decision = group.observe(
        now=20.0,
        continuous={"cpu": 40.0},
        requested_profile=PublicationProfile.DETAIL,
    )

    assert decision.publish is True
    assert decision.profile is PublicationProfile.DETAIL
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


def test_manual_refresh_emits_current_sample_without_waiting_for_window():
    group = AdaptiveGroup()
    group.observe(now=0.0, continuous={"cpu": 10.0})

    decision = group.observe(now=10.0, continuous={"cpu": 42.0}, manual=True)

    assert decision.publish is True
    assert decision.reason == "manual_refresh"
    assert decision.values["cpu"] == 42.0
