from app.disk_health import disk_temperature_limits
from app.presentation import PublicationProfile
from app.presentation_policy import (
    cpu_profile_selector,
    disk_profile_selector,
    gpu_profile_selector,
    memory_profile_selector,
    ups_profile_selector,
)


def test_cpu_profile_uses_fast_60_second_rolling_average_and_strict_threshold():
    selector = cpu_profile_selector()

    first = selector.observe(now=0.0, metrics={"usage": 70.0, "temperature": 60.0})
    assert first.profile is PublicationProfile.NORMAL

    equality = selector.observe(now=30.0, metrics={"usage": 80.0, "temperature": 60.0})
    assert equality.averages["usage"] == 75.0
    assert equality.profile is PublicationProfile.NORMAL

    detail = selector.observe(now=60.0, metrics={"usage": 90.0, "temperature": 60.0})
    assert detail.averages["usage"] == 80.0
    assert detail.profile is PublicationProfile.DETAIL
    assert detail.reason == "usage"


def test_cpu_throttling_is_immediate_detail_without_waiting_for_average():
    selector = cpu_profile_selector()

    decision = selector.observe(
        now=0.0,
        metrics={"usage": 10.0, "temperature": 50.0},
        flags={"throttling": True},
    )

    assert decision.profile is PublicationProfile.DETAIL
    assert decision.reason == "throttling"


def test_memory_uses_fast_decision_window():
    selector = memory_profile_selector()

    assert selector.observe(now=0.0, metrics={"usage": 90.0}).profile is PublicationProfile.NORMAL
    assert selector.observe(now=61.0, metrics={"usage": 93.0}).profile is PublicationProfile.DETAIL


def test_disk_temperature_limits_are_shared_with_health_policy():
    assert disk_temperature_limits("HDD") == (50.0, 60.0)
    assert disk_temperature_limits("SSD") == (70.0, 80.0)
    assert disk_temperature_limits("NVMe") == (75.0, 85.0)
    assert disk_temperature_limits("other") == (70.0, 85.0)


def test_disk_profile_uses_slow_five_minute_window_and_is_isolated_per_disk():
    hot = disk_profile_selector("NVMe")
    cool = disk_profile_selector("NVMe")

    hot.observe(now=0.0, metrics={"temperature": 70.0})
    cool.observe(now=0.0, metrics={"temperature": 45.0})

    hot_decision = hot.observe(now=300.1, metrics={"temperature": 80.0})
    cool_decision = cool.observe(now=300.1, metrics={"temperature": 45.0})

    assert hot_decision.profile is PublicationProfile.DETAIL
    assert cool_decision.profile is PublicationProfile.NORMAL


def test_gpu_profile_uses_slow_five_minute_window():
    active = gpu_profile_selector()
    idle = gpu_profile_selector()

    active.observe(now=0.0, metrics={"temperature": 60.0, "load": 0.0})
    idle.observe(now=0.0, metrics={"temperature": 60.0, "load": 0.0})

    assert active.observe(
        now=300.1, metrics={"temperature": 60.0, "load": 30.0}
    ).profile is PublicationProfile.DETAIL
    assert idle.observe(
        now=300.1, metrics={"temperature": 60.0, "load": 0.0}
    ).profile is PublicationProfile.NORMAL


def test_ups_discrete_conditions_use_detail_not_extra_profiles():
    selector = ups_profile_selector()

    on_battery = selector.observe(now=0.0, metrics={"load": 20.0}, flags={"on_battery": True})
    assert on_battery.profile is PublicationProfile.DETAIL
    assert on_battery.reason == "on_battery"

    low_battery = selector.observe(
        now=1.0,
        metrics={"load": 20.0},
        flags={"on_battery": True, "low_battery": True},
    )
    assert low_battery.profile is PublicationProfile.DETAIL
    assert low_battery.reason in {"on_battery", "low_battery"}
