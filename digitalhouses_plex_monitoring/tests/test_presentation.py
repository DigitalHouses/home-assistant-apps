from app.presentation import AdaptiveGroup, ProfileWindows, PublicationProfile


def test_publication_profiles_match_linux_agent_contract():
    assert {item.value for item in PublicationProfile} == {
        "normal",
        "detail",
        "playback",
    }


def test_publication_windows_match_linux_agent_contract():
    windows = ProfileWindows()

    assert windows.normal_seconds == 900.0
    assert windows.detail_seconds == 300.0
    assert windows.playback_seconds == 30.0


def test_normal_profile_publishes_window_average():
    group = AdaptiveGroup(initial_profile=PublicationProfile.NORMAL)

    startup = group.observe(now=0.0, continuous={"cpu": 10.0})
    assert startup.publish is True
    assert startup.values["cpu"] == 10.0

    assert group.observe(now=300.0, continuous={"cpu": 20.0}).publish is False
    assert group.observe(now=600.0, continuous={"cpu": 30.0}).publish is False

    decision = group.observe(now=900.0, continuous={"cpu": 40.0})
    assert decision.publish is True
    assert decision.reason == "average_window_complete"
    assert decision.values["cpu"] == 30.0


def test_detail_profile_publishes_five_minute_average():
    group = AdaptiveGroup(initial_profile=PublicationProfile.DETAIL)

    group.observe(now=0.0, continuous={"cpu": 10.0})
    group.observe(now=100.0, continuous={"cpu": 20.0})
    group.observe(now=200.0, continuous={"cpu": 40.0})

    decision = group.observe(now=300.0, continuous={"cpu": 60.0})
    assert decision.publish is True
    assert decision.values["cpu"] == 40.0


def test_discrete_change_is_immediate():
    group = AdaptiveGroup()

    group.observe(
        now=0.0,
        continuous={"cpu": 10.0},
        discrete={"transcoding": False},
    )
    decision = group.observe(
        now=10.0,
        continuous={"cpu": 20.0},
        discrete={"transcoding": True},
    )

    assert decision.publish is True
    assert decision.reason == "change"
    assert decision.values["transcoding"] is True


def test_manual_refresh_uses_current_sample():
    group = AdaptiveGroup()
    group.observe(now=0.0, continuous={"cpu": 10.0})

    decision = group.observe(now=10.0, continuous={"cpu": 42.0}, manual=True)

    assert decision.publish is True
    assert decision.reason == "manual_refresh"
    assert decision.values["cpu"] == 42.0
