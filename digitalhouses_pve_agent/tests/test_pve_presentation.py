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


def cpu_state(usage=20.0, temperature=55.0, throttling=False):
    return subsystem(
        {
            "usage_percent": usage,
            "temperature_c": temperature,
            "frequency": {"average_mhz": 1800.0},
            "throttling_active": throttling,
        }
    )


def test_cpu_rolling_average_profile_transition_publishes_only_cpu():
    router = PvePresentationRouter()

    router.route(
        {"cpu": cpu_state(usage=70.0)},
        selected=("cpu",),
        now=0.0,
        collected_at="2026-09-14T20:00:00+05:00",
        last_refresh=None,
        force=True,
    )
    decision = router.route(
        {"cpu": cpu_state(usage=90.0)},
        selected=("cpu",),
        now=60.1,
        collected_at="2026-09-14T20:01:00+05:00",
        last_refresh=None,
    )

    assert groups(decision) == {"cpu"}
    assert decision[0].profile is PublicationProfile.DETAIL
    assert decision[0].reason == "profile_transition"


def test_cpu_throttling_immediately_publishes_cpu_detail():
    router = PvePresentationRouter()
    router.route(
        {"cpu": cpu_state()}, selected=("cpu",), now=0.0,
        collected_at="2026-09-14T20:00:00+05:00", last_refresh=None, force=True,
    )

    decision = router.route(
        {"cpu": cpu_state(usage=25.0, temperature=70.0, throttling=True)},
        selected=("cpu",), now=10.0,
        collected_at="2026-09-14T20:00:10+05:00", last_refresh=None,
    )

    assert groups(decision) == {"cpu"}
    assert decision[0].profile is PublicationProfile.DETAIL
    assert decision[0].payload["subsystems"]["cpu"]["data"]["throttling_active"] is True


def test_slow_disk_temperature_drives_disk_telemetry_not_hourly_smart_snapshot():
    router = PvePresentationRouter()
    cool = subsystem(
        {
            "nvme0": {
                "disk_id": "nvme0",
                "disk_type": "NVMe",
                "temperature_c": 70.0,
                "model": "A",
                "available": True,
            }
        }
    )
    hot = subsystem(
        {
            "nvme0": {
                "disk_id": "nvme0",
                "disk_type": "NVMe",
                "temperature_c": 80.0,
                "model": "A",
                "available": True,
            }
        }
    )

    router.route(
        {"disk_temperature": cool}, selected=("disk_temperature",), now=0.0,
        collected_at="2026-09-14T20:00:00+05:00", last_refresh=None, force=True,
    )
    decision = router.route(
        {"disk_temperature": hot}, selected=("disk_temperature",), now=300.1,
        collected_at="2026-09-14T20:05:00+05:00", last_refresh=None,
    )

    assert groups(decision) == {"disk/nvme0/telemetry"}
    publication = decision[0]
    assert publication.profile is PublicationProfile.DETAIL
    assert publication.payload["subsystems"]["smart"]["data"]["nvme0"]["temperature_c"] == 80.0


def test_smart_health_is_change_only_and_does_not_drive_disk_temperature_profile():
    router = PvePresentationRouter()
    smart = subsystem(
        {
            "nvme0": {
                "disk_id": "nvme0",
                "disk_type": "NVMe",
                "temperature_c": 90.0,
                "health_state": "HEALTHY",
                "available": True,
            }
        }
    )

    decision = router.route(
        {"smart": smart}, selected=("smart",), now=0.0,
        collected_at="2026-09-14T20:00:00+05:00", last_refresh=None, force=True,
    )

    assert groups(decision) == {"collector/smart", "disk/nvme0/status"}
    assert "disk:nvme0" not in router.profile_summary()["resources"]


def test_cpu_detail_does_not_change_gpu_or_storage_profile():
    router = PvePresentationRouter()
    states = {
        "cpu": cpu_state(usage=70.0),
        "gpu": subsystem(
            {
                "gpu0": {
                    "gpu_id": "gpu0",
                    "temperature_c": 55.0,
                    "transcoding_load_percent": 0.0,
                    "model": "iGPU",
                }
            }
        ),
        "storage": subsystem(
            {"local": {"name": "local", "usage_percent": 40.0, "total_gib": 100.0}}
        ),
    }
    router.route(
        states, selected=("cpu", "gpu", "storage"), now=0.0,
        collected_at="2026-09-14T20:00:00+05:00", last_refresh=None, force=True,
    )
    states["cpu"] = cpu_state(usage=90.0)
    router.route(
        states, selected=("cpu",), now=60.1,
        collected_at="2026-09-14T20:01:00+05:00", last_refresh=None,
    )

    summary = router.profile_summary()
    assert summary["resources"]["cpu"] == "detail"
    assert summary["resources"]["gpu:gpu0"] == "normal"
    assert summary["resources"]["storage"] == "normal"


def test_manual_refresh_emits_current_groups_without_waiting_for_average_windows():
    router = PvePresentationRouter()
    states = {
        "cpu": cpu_state(usage=10.0, temperature=50.0),
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


def test_profile_summary_reports_detail_as_highest_active_profile():
    router = PvePresentationRouter()
    router.route(
        {"cpu": cpu_state(throttling=True), "memory": subsystem({"usage_percent": 80.0})},
        selected=("cpu", "memory"), now=0.0,
        collected_at="2026-09-14T20:00:00+05:00", last_refresh=None, force=True,
    )
    summary = router.profile_summary()

    assert summary["state"] == "detail"
    assert summary["resources"]["cpu"] == "detail"
    assert summary["resources"]["memory"] == "normal"
    assert summary["reason"] == "cpu:throttling"


def test_fan_summary_is_not_mistaken_for_fan_objects():
    router = PvePresentationRouter()
    fans = subsystem(
        {
            "detected": True,
            "count": 1,
            "candidate_count": 2,
            "confirmed_count": 1,
            "unconfirmed_count": 1,
            "status": "Detected",
            "nct6798_fan1": {
                "fan_id": "nct6798_fan1",
                "name": "nct6798 fan1",
                "label": "CPU fan",
                "source": "hwmon",
                "rpm": 1250.0,
            },
        }
    )

    decision = router.route(
        {"fans": fans}, selected=("fans",), now=0.0,
        collected_at="2026-09-14T20:00:00+05:00", last_refresh=None, force=True,
    )

    assert groups(decision) == {"collector/fans", "fans", "fan/nct6798_fan1"}
    summary = next(item for item in decision if item.group == "fans")
    assert summary.payload["subsystems"]["fans"]["data"] == {
        "detected": True,
        "count": 1,
        "candidate_count": 2,
        "confirmed_count": 1,
        "unconfirmed_count": 1,
        "status": "Detected",
    }


def test_host_inventory_and_shutdown_history_publish_as_independent_groups():
    router = PvePresentationRouter()
    host = subsystem(
        {
            "hostname": "pve",
            "model": "MINI S",
            "shutdown_history": {
                "history_count": 2,
                "previous_shutdown": {"shutdown_class": "clean", "shutdown_reason": "user"},
            },
        }
    )

    decision = router.route(
        {"host": host}, selected=("host",), now=0.0,
        collected_at="2026-09-14T20:00:00+05:00", last_refresh=None, force=True,
    )

    assert groups(decision) == {"collector/host", "host", "shutdown"}
