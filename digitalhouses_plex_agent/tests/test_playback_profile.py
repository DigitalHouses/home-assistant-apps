from app.models import (
    ActivityState,
    CpuGroupMetrics,
    CpuMetrics,
    MonitorSnapshot,
)
from app.presentation import AdaptiveGroup, ProfileWindows, PublicationProfile
from app.presentation_plex import PlexPresentationRouter
from app.presentation_policy import PlexProfileSelector


def snapshot(*, cpu=20.0, scanner=False, transcoder=False):
    return MonitorSnapshot(
        collected_at="2026-09-22T00:00:00+00:00",
        activity=ActivityState(
            plex_server_running=True,
            scanner_running=scanner,
            credits_detection=False,
            intro_detection=False,
            thumbnail_generation=False,
            transcoder_running=transcoder,
            activity="transcoding" if transcoder else ("scanning" if scanner else "idle"),
            scanner_actions=("scan",) if scanner else (),
            current_item="movie.mkv" if transcoder else None,
        ),
        cpu=CpuMetrics(
            CpuGroupMetrics(cpu, cpu, cpu),
            CpuGroupMetrics(cpu if scanner else 0.0, cpu if scanner else 0.0, cpu if scanner else 0.0),
            CpuGroupMetrics(cpu if transcoder else 0.0, cpu if transcoder else 0.0, cpu if transcoder else 0.0),
        ),
        process_count=2 if transcoder else 1,
        collector_status="ok",
        last_refresh=None,
    )


def api_payload(*, playback=False):
    count = 1 if playback else 0
    return {
        "plex_api_status": "ok",
        "playback_count": count,
        "playback_sessions_state": "1 session" if playback else "0 sessions",
        "playback_active": playback,
        "video_playback_count": count,
        "audio_playback_count": 0,
        "video_playback_active": playback,
        "audio_playback_active": False,
        "hardware_transcode_active": False,
        "playback_sessions": [{"title": "Movie"}] if playback else [],
        "library_count": 0,
        "libraries": [],
        "libraries_by_id": {},
    }


def gpu_payload(value):
    return {
        "supported": True,
        "available": True,
        "status": "ok",
        "source": "intel_gpu_top",
        "pci_address": "0000:00:10.0",
        "video_busy_percent": value,
        "render_busy_percent": value,
        "video_enhance_busy_percent": 0.0,
        "frequency_mhz": 700.0,
        "rc6_percent": 10.0,
        "temperature_c": None,
    }


def test_playback_profile_and_window_contract():
    assert {item.value for item in PublicationProfile} == {
        "normal",
        "detail",
        "playback",
    }

    windows = ProfileWindows()
    assert windows.normal_seconds == 900.0
    assert windows.detail_seconds == 300.0
    assert windows.playback_seconds == 30.0
    assert windows.seconds(PublicationProfile.PLAYBACK) == 30.0


def test_selector_uses_playback_for_playback_or_transcoder():
    selector = PlexProfileSelector()

    playback = selector.observe(
        now=0.0,
        cpu_percent=20.0,
        scanner_running=False,
        transcoder_running=False,
        playback_active=True,
    )
    assert playback.profile is PublicationProfile.PLAYBACK
    assert playback.reason == "playback_active"

    transcoder = selector.observe(
        now=10.0,
        cpu_percent=20.0,
        scanner_running=False,
        transcoder_running=True,
        playback_active=True,
    )
    assert transcoder.profile is PublicationProfile.PLAYBACK
    assert transcoder.reason == "transcoder_running"


def test_selector_keeps_detail_for_scanner_or_high_cpu_without_playback():
    scanner = PlexProfileSelector().observe(
        now=0.0,
        cpu_percent=20.0,
        scanner_running=True,
        transcoder_running=False,
        playback_active=False,
    )
    assert scanner.profile is PublicationProfile.DETAIL
    assert scanner.reason == "scanner_running"

    high_cpu = PlexProfileSelector().observe(
        now=0.0,
        cpu_percent=90.0,
        scanner_running=False,
        transcoder_running=False,
        playback_active=False,
    )
    assert high_cpu.profile is PublicationProfile.DETAIL
    assert high_cpu.reason == "high_cpu"


def test_playback_window_publishes_30_second_average():
    group = AdaptiveGroup(
        initial_profile=PublicationProfile.PLAYBACK,
        source_interval_seconds=10.0,
    )

    assert group.observe(now=0.0, continuous={"value": 10.0}).publish is True
    assert group.observe(now=10.0, continuous={"value": 20.0}).publish is False
    assert group.observe(now=20.0, continuous={"value": 30.0}).publish is False

    decision = group.observe(now=30.0, continuous={"value": 40.0})
    assert decision.publish is True
    assert decision.reason == "average_window_complete"
    assert decision.values["value"] == 30.0


def test_router_enters_playback_immediately_then_publishes_cpu_and_gpu_at_30s():
    router = PlexPresentationRouter(source_interval_seconds=10.0)

    router.route(
        snapshot(cpu=10.0),
        api_payload(playback=False),
        gpu_payload(0.0),
        now=0.0,
        force=True,
    )

    entered = router.route(
        snapshot(cpu=30.0),
        api_payload(playback=True),
        gpu_payload(30.0),
        now=10.0,
    )
    entered_by_group = {item.group: item for item in entered}

    assert entered_by_group["cpu"].profile is PublicationProfile.PLAYBACK
    assert entered_by_group["cpu"].reason == "profile_transition"
    assert entered_by_group["gpu"].profile is PublicationProfile.PLAYBACK
    assert entered_by_group["gpu"].reason == "profile_transition"

    at_20 = router.route(
        snapshot(cpu=40.0),
        api_payload(playback=True),
        gpu_payload(40.0),
        now=20.0,
    )
    assert "cpu" not in {item.group for item in at_20}
    assert "gpu" not in {item.group for item in at_20}

    at_30 = router.route(
        snapshot(cpu=50.0),
        api_payload(playback=True),
        gpu_payload(50.0),
        now=30.0,
    )
    assert "cpu" not in {item.group for item in at_30}
    assert "gpu" not in {item.group for item in at_30}

    at_40 = router.route(
        snapshot(cpu=60.0),
        api_payload(playback=True),
        gpu_payload(60.0),
        now=40.0,
    )
    published = {item.group: item for item in at_40}

    assert published["cpu"].profile is PublicationProfile.PLAYBACK
    assert published["gpu"].profile is PublicationProfile.PLAYBACK
    assert published["cpu"].payload["cpu"] == 50.0
    assert published["gpu"].payload["video_busy_percent"] == 50.0


def test_router_leaves_playback_immediately_and_keeps_collection_cadence():
    router = PlexPresentationRouter(source_interval_seconds=10.0)

    router.route(
        snapshot(cpu=20.0),
        api_payload(playback=True),
        gpu_payload(20.0),
        now=0.0,
        force=True,
    )

    left = router.route(
        snapshot(cpu=20.0),
        api_payload(playback=False),
        gpu_payload(0.0),
        now=10.0,
    )
    by_group = {item.group: item for item in left}

    assert by_group["cpu"].profile is PublicationProfile.NORMAL
    assert by_group["cpu"].reason == "profile_transition"
    assert by_group["gpu"].profile is PublicationProfile.NORMAL
    assert by_group["gpu"].reason == "profile_transition"
    assert router.source_interval_seconds == 10.0
