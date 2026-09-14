from app.presentation import PublicationProfile
from app.presentation_pve import PresentationSubsystem, PvePresentationRouter


def subsystem(data, *, available=True, error=None):
    return PresentationSubsystem(
        available=available,
        data=data,
        last_success="2026-09-14T20:00:00+05:00",
        error=error,
    )


def groups(publications):
    return {item.group for item in publications}


def test_cpu_load_profile_transition_publishes_cpu_not_other_resources():
    router = PvePresentationRouter()
    cpu = subsystem(
        {
            "usage_percent": 80.0,
            "temperature_c": 60.0,
            "frequency": {"average_mhz": 2200.0},
            "throttling_active": False,
        }
    )

    router.route(
        {"cpu": cpu},
        selected=("cpu",),
        now=0.0,
        collected_at="2026-09-14T20:00:00+05:00",
        last_refresh=None,
        force=True,
    )
    decision = router.route(
        {"cpu": cpu},
        selected=("cpu",),
        now=60.0,
        collected_at="2026-09-14T20:01:00+05:00",
        last_refresh=None,
    )

    assert groups(decision) == {"cpu"}
    cpu_publication = decision[0]
    assert cpu_publication.profile is PublicationProfile.HIGH
    assert cpu_publication.reason == "profile_transition"


def test_cpu_throttling_immediately_publishes_cpu_critical():
    router = PvePresentationRouter()
    normal = subsystem(
        {
            "usage_percent": 20.0,
            "temperature_c": 55.0,
            "frequency": {"average_mhz": 1200.0},
            "throttling_active": False,
        }
    )
    throttled = subsystem(
        {
            "usage_percent": 25.0,
            "temperature_c": 70.0,
            "frequency": {"average_mhz": 900.0},
            "throttling_active": True,
        }
    )

    router.route(
        {"cpu": normal}, selected=("cpu",), now=0.0,
        collected_at="2026-09-14T20:00:00+05:00", last_refresh=None, force=True,
    )
    decision = router.route(
        {"cpu": throttled}, selected=("cpu",), now=10.0,
        collected_at="2026-09-14T20:00:10+05:00", last_refresh=None,
    )

    assert groups(decision) == {"cpu"}
    assert decision[0].profile is PublicationProfile.CRITICAL
    assert decision[0].payload["subsystems"]["cpu"]["data"]["throttling_active"] is True


def test_one_hot_disk_only_accelerates_that_disk_telemetry():
    router = PvePresentationRouter()
    initial = subsystem(
        {
            "nvme_hot": {
                "disk_id": "nvme_hot",
                "disk_type": "NVMe",
                "temperature_c": 80.0,
                "health_state": "HEALTHY",
                "model": "A",
            },
            "nvme_cool": {
                "disk_id": "nvme_cool",
                "disk_type": "NVMe",
                "temperature_c": 45.0,
                "health_state": "HEALTHY",
                "model": "B",
            },
        }
    )

    router.route(
        {"smart": initial}, selected=("smart",), now=0.0,
        collected_at="2026-09-14T20:00:00+05:00", last_refresh=None, force=True,
    )
    decision = router.route(
        {"smart": initial}, selected=("smart",), now=180.0,
        collected_at="2026-09-14T20:03:00+05:00", last_refresh=None,
    )

    assert groups(decision) == {"disk/nvme_hot/telemetry"}
    assert decision[0].profile is PublicationProfile.HIGH


def test_manual_refresh_emits_current_groups_without_waiting_for_average_windows():
    router = PvePresentationRouter()
    states = {
        "cpu": subsystem(
            {
                "usage_percent": 10.0,
                "temperature_c": 50.0,
                "frequency": {"average_mhz": 1000.0},
                "throttling_active": False,
            }
        ),
        "memory": subsystem(
            {"usage_percent": 80.0, "swap_usage_percent": 0.0, "total_gib": 16.0}
        ),
    }

    router.route(
        states, selected=("cpu", "memory"), now=0.0,
        collected_at="2026-09-14T20:00:00+05:00", last_refresh=None, force=True,
    )
    decision = router.route(
        states, selected=("cpu", "memory"), now=10.0,
        collected_at="2026-09-14T20:00:10+05:00",
        last_refresh="2026-09-14T20:00:10+05:00",
        manual=True,
    )

    assert groups(decision) == {"cpu", "memory", "collector/cpu", "collector/memory"}
    assert all(item.reason == "manual_refresh" for item in decision)


def test_profile_summary_reports_maximum_active_resource_profile():
    router = PvePresentationRouter()
    cpu = subsystem(
        {
            "usage_percent": 10.0,
            "temperature_c": 50.0,
            "frequency": {"average_mhz": 1000.0},
            "throttling_active": True,
        }
    )
    memory = subsystem({"usage_percent": 80.0, "swap_usage_percent": 0.0})

    router.route(
        {"cpu": cpu, "memory": memory}, selected=("cpu", "memory"), now=0.0,
        collected_at="2026-09-14T20:00:00+05:00", last_refresh=None, force=True,
    )
    summary = router.profile_summary()

    assert summary["state"] == "critical"
    assert summary["resources"]["cpu"] == "critical"
    assert summary["resources"]["memory"] == "normal"
    assert summary["reason"] == "cpu:throttling"
