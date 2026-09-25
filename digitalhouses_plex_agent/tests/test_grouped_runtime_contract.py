from app.models import (
    ActivityState,
    BuildInfo,
    CpuGroupMetrics,
    CpuMetrics,
    MonitorSnapshot,
)
from app.presentation_runtime import PlexPublicationRuntime


class FakeBridge:
    def __init__(self):
        self.groups = []
        self.failed_group = None

    def publish_state_group(self, group, payload):
        self.groups.append((group, payload))
        return group != self.failed_group


def snapshot(
    *,
    cpu=20.0,
    activity="idle",
    transcoder=False,
    scanner=False,
    refresh=None,
):
    return MonitorSnapshot(
        collected_at="2026-09-21T09:00:00+00:00",
        activity=ActivityState(
            plex_server_running=True,
            scanner_running=scanner,
            credits_detection=False,
            intro_detection=False,
            thumbnail_generation=False,
            transcoder_running=transcoder,
            activity=activity,
            scanner_actions=(),
            current_item=None,
        ),
        cpu=CpuMetrics(
            CpuGroupMetrics(cpu, cpu, cpu),
            CpuGroupMetrics(0.0, 0.0, 0.0),
            CpuGroupMetrics(cpu if transcoder else 0.0, cpu if transcoder else 0.0, cpu if transcoder else 0.0),
        ),
        process_count=1,
        collector_status="ok",
        last_refresh=refresh,
    )


def api_payload(*, playback=False, status="ok"):
    count = 1 if playback else 0
    return {
        "plex_api_status": status,
        "playback_count": count,
        "playback_sessions_state": "1 session" if playback else "0 sessions",
        "playback_active": playback,
        "video_playback_count": count,
        "audio_playback_count": 0,
        "video_playback_active": playback,
        "audio_playback_active": False,
        "playback_sessions": [{"title": "Movie"}] if playback else [],
        "library_count": 1,
        "libraries": [{"section_id": "1", "title": "Movies", "item_count": 10}],
        "libraries_by_id": {
            "1": {"section_id": "1", "title": "Movies", "item_count": 10}
        },
    }


def make_runtime(mono_values):
    values = iter(mono_values)
    bridge = FakeBridge()
    runtime = PlexPublicationRuntime(
        bridge=bridge,
        build=BuildInfo(
            "0.3.0",
            "digitalhouses_plex_agent-v0.3.0",
            "0123456789abcdef",
        ),
        source_interval_seconds=10.0,
        now_monotonic=lambda: next(values),
    )
    return runtime, bridge


def test_startup_publishes_independent_groups_and_diagnostics():
    runtime, bridge = make_runtime([100.0, 100.0])

    assert runtime.publish_snapshot(snapshot(), api_payload(), force=True) is True

    groups = [group for group, _ in bridge.groups]
    assert groups == ["activity", "cpu", "playback", "libraries", "gpu", "diagnostics"]


def test_diagnostics_expose_version_uptime_and_no_commit():
    runtime, bridge = make_runtime([100.0, 105.0])

    runtime.publish_snapshot(snapshot(), api_payload(), force=True)
    diagnostics = dict(bridge.groups)["diagnostics"]

    assert diagnostics["agent_version"] == "0.3.0"
    assert diagnostics["agent_uptime_seconds"] == 5
    assert "commit" not in diagnostics
    assert "build_commit" not in diagnostics


def test_transcoding_moves_cpu_presentation_to_playback_without_changing_collection_interval():
    runtime, bridge = make_runtime([0.0, 0.0, 10.0])

    runtime.publish_snapshot(snapshot(cpu=10.0), api_payload(), force=True)
    bridge.groups.clear()

    runtime.publish_snapshot(
        snapshot(cpu=80.0, activity="transcoding", transcoder=True),
        api_payload(),
    )

    published = dict(bridge.groups)
    assert published["diagnostics"]["publication_profile"]["state"] == "playback"
    assert published["diagnostics"]["publication_profile"]["reason"] == "transcoder_running"
    assert runtime.source_interval_seconds == 10.0


def test_reconnect_republishes_cached_groups_without_recollecting():
    runtime, bridge = make_runtime([0.0, 0.0, 5.0])

    runtime.publish_snapshot(snapshot(), api_payload(), force=True)
    cached = [group for group, _ in bridge.groups]
    bridge.groups.clear()

    assert runtime.republish_cached() is True
    assert [group for group, _ in bridge.groups] == cached


def test_failed_group_is_retried_independently():
    runtime, bridge = make_runtime([0.0, 0.0, 10.0, 10.0])
    bridge.failed_group = "cpu"

    assert runtime.publish_snapshot(snapshot(), api_payload(), force=True) is False
    assert "cpu" in runtime.pending_groups
    bridge.groups.clear()

    bridge.failed_group = None
    assert runtime.retry_pending() is True

    assert [group for group, _ in bridge.groups] == ["cpu", "diagnostics"]


def test_uptime_heartbeat_updates_only_diagnostics():
    runtime, bridge = make_runtime([0.0, 0.0, 61.0])

    runtime.publish_snapshot(snapshot(), api_payload(), force=True)
    bridge.groups.clear()

    assert runtime.publish_uptime_heartbeat() is True
    assert [group for group, _ in bridge.groups] == ["diagnostics"]
    assert bridge.groups[0][1]["agent_uptime_seconds"] == 61


def test_failed_gpu_group_is_retried_independently():
    runtime, bridge = make_runtime([0.0, 0.0, 10.0, 10.0])
    bridge.failed_group = "gpu"

    assert runtime.publish_snapshot(snapshot(), api_payload(), force=True) is False
    assert "gpu" in runtime.pending_groups
    bridge.groups.clear()

    bridge.failed_group = None
    assert runtime.retry_pending() is True

    assert [group for group, _ in bridge.groups] == ["gpu", "diagnostics"]
