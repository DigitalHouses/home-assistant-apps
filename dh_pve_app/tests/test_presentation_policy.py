from app.presentation import PublicationProfile
from app.presentation_policy import (
    cpu_profile_selector,
    disk_profile_selector,
    gpu_profile_selector,
    memory_profile_selector,
    ups_profile_selector,
)
from app.disk_health import disk_temperature_limits


def test_cpu_numeric_load_requires_decision_window_before_high_profile():
    selector = cpu_profile_selector()

    first = selector.observe(now=0.0, metrics={"usage": 80.0, "temperature": 60.0})
    assert first.profile is PublicationProfile.NORMAL

    middle = selector.observe(now=30.0, metrics={"usage": 80.0, "temperature": 60.0})
    assert middle.profile is PublicationProfile.NORMAL

    ready = selector.observe(now=60.0, metrics={"usage": 80.0, "temperature": 60.0})
    assert ready.profile is PublicationProfile.HIGH
    assert ready.reason == "usage"


def test_cpu_throttling_is_immediate_critical_without_decision_window():
    selector = cpu_profile_selector()

    decision = selector.observe(
        now=0.0,
        metrics={"usage": 10.0, "temperature": 50.0},
        flags={"throttling": True},
    )

    assert decision.profile is PublicationProfile.CRITICAL
    assert decision.reason == "throttling"


def test_cpu_critical_uses_hysteresis_before_downgrading():
    selector = cpu_profile_selector()

    selector.observe(now=0.0, metrics={"usage": 98.0, "temperature": 60.0})
    critical = selector.observe(now=60.0, metrics={"usage": 98.0, "temperature": 60.0})
    assert critical.profile is PublicationProfile.CRITICAL

    hold = selector.observe(now=61.0, metrics={"usage": 84.0, "temperature": 60.0})
    assert hold.profile is PublicationProfile.CRITICAL

    selector.observe(now=122.0, metrics={"usage": 84.0, "temperature": 60.0})
    downgraded = selector.observe(now=183.0, metrics={"usage": 84.0, "temperature": 60.0})
    assert downgraded.profile is PublicationProfile.HIGH


def test_ram_at_90_percent_is_normal_but_sustained_93_percent_is_high():
    selector = memory_profile_selector()

    selector.observe(now=0.0, metrics={"usage": 90.0})
    normal = selector.observe(now=120.0, metrics={"usage": 90.0})
    assert normal.profile is PublicationProfile.NORMAL

    selector.observe(now=121.0, metrics={"usage": 93.0})
    high = selector.observe(now=241.0, metrics={"usage": 93.0})
    assert high.profile is PublicationProfile.HIGH


def test_disk_temperature_limits_are_shared_with_health_policy():
    assert disk_temperature_limits("HDD") == (50.0, 60.0)
    assert disk_temperature_limits("SSD") == (70.0, 80.0)
    assert disk_temperature_limits("NVMe") == (75.0, 85.0)
    assert disk_temperature_limits("other") == (70.0, 85.0)


def test_hot_nvme_enters_high_without_affecting_another_disk_selector():
    hot = disk_profile_selector("NVMe")
    cool = disk_profile_selector("NVMe")

    hot.observe(now=0.0, metrics={"temperature": 80.0})
    cool.observe(now=0.0, metrics={"temperature": 45.0})

    hot_decision = hot.observe(now=180.0, metrics={"temperature": 80.0})
    cool_decision = cool.observe(now=180.0, metrics={"temperature": 45.0})

    assert hot_decision.profile is PublicationProfile.HIGH
    assert cool_decision.profile is PublicationProfile.NORMAL


def test_gpu_transcoding_can_raise_only_its_own_selector_to_high():
    active = gpu_profile_selector()
    idle = gpu_profile_selector()

    active.observe(now=0.0, metrics={"temperature": 60.0, "load": 30.0})
    idle.observe(now=0.0, metrics={"temperature": 60.0, "load": 0.0})

    assert active.observe(
        now=60.0, metrics={"temperature": 60.0, "load": 30.0}
    ).profile is PublicationProfile.HIGH
    assert idle.observe(
        now=60.0, metrics={"temperature": 60.0, "load": 0.0}
    ).profile is PublicationProfile.NORMAL


def test_ups_discrete_conditions_escalate_immediately():
    selector = ups_profile_selector()

    on_battery = selector.observe(now=0.0, metrics={"load": 20.0}, flags={"on_battery": True})
    assert on_battery.profile is PublicationProfile.HIGH
    assert on_battery.reason == "on_battery"

    low_battery = selector.observe(
        now=1.0,
        metrics={"load": 20.0},
        flags={"on_battery": True, "low_battery": True},
    )
    assert low_battery.profile is PublicationProfile.CRITICAL
    assert low_battery.reason == "low_battery"
