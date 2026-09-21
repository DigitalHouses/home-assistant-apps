from pathlib import Path
from tempfile import TemporaryDirectory

from app.api_runtime import PlexApiRuntime
from app.config import load_config
from app.discovery import build_discovery_payload
from app.metrics import group_current_cpu
from app.models import BuildInfo, ProcessSample
from app.plex_api import PlaybackSession
from app.presentation_runtime import PlexPublicationRuntime


class FakeCollector:
    def __init__(self):
        self.sessions = ()
        self.libraries = ()

    def collect_playback(self):
        return self.sessions

    def collect_libraries(self):
        return self.libraries


class FakeBridge:
    def publish_state_group(self, group, payload):
        return True


def _config(tmp: str):
    path = Path(tmp) / "app.conf"
    path.write_text("[mqtt]\nhost = mqtt\n", encoding="utf-8")
    return load_config(path)


def _session(session_id: str):
    return PlaybackSession(
        session_id=session_id,
        content_type="video",
        media_type="movie",
        title="Movie",
        mode="Direct Play",
    )


def test_cpu_is_normalized_to_complete_machine_capacity():
    processes = [
        ProcessSample(1, 1.0, "Plex Media Server", (), 100.0),
        ProcessSample(2, 1.0, "Plex Media Scanner", (), 200.0),
        ProcessSample(3, 1.0, "Plex Transcoder", (), 100.0),
    ]
    total, scanner, transcoder = group_current_cpu(
        processes,
        logical_cpu_count=4,
    )
    assert total == 100.0
    assert scanner == 50.0
    assert transcoder == 25.0


def test_cpu_normalization_is_clamped_to_100_percent():
    processes = [
        ProcessSample(1, 1.0, "Plex Media Server", (), 500.0),
    ]
    assert group_current_cpu(processes, logical_cpu_count=4)[0] == 100.0


def test_discovery_keeps_only_current_cpu_entities_and_adds_timestamps():
    with TemporaryDirectory() as tmp:
        config = _config(tmp)
        build = BuildInfo("0.5.0", "digitalhouses_plex_agent-v0.5.0", "a" * 40)
        components = build_discovery_payload(config, build)["components"]

    for key in ("cpu", "scanner_cpu", "transcoder_cpu"):
        assert key in components
        assert components[key]["unit_of_measurement"] == "%"

    for key in (
        "cpu_avg",
        "cpu_max",
        "scanner_cpu_avg",
        "scanner_cpu_max",
        "transcoder_cpu_avg",
        "transcoder_cpu_max",
    ):
        assert key not in components

    assert components["agent_started_at"]["default_entity_id"] == (
        "sensor.dh_plex_agent_started_at"
    )
    assert components["agent_started_at"]["device_class"] == "timestamp"
    assert components["playback_started_at"]["default_entity_id"] == (
        "sensor.dh_plex_playback_started_at"
    )
    assert components["playback_started_at"]["device_class"] == "timestamp"


def test_agent_started_at_is_published_as_diagnostic_timestamp_value():
    runtime = PlexPublicationRuntime(
        bridge=FakeBridge(),
        build=BuildInfo("0.5.0", "tag", "a" * 40),
        source_interval_seconds=10.0,
        now_monotonic=lambda: 100.0,
        agent_started_at="2026-09-22T00:00:00+00:00",
    )
    payload = runtime._diagnostics_payload(110.0)
    assert payload["agent_started_at"] == "2026-09-22T00:00:00+00:00"
    assert payload["agent_uptime_seconds"] == 10


def test_playback_started_at_tracks_earliest_active_session_and_clears():
    with TemporaryDirectory() as tmp:
        collector = FakeCollector()
        times = iter(
            (
                "2026-09-22T00:00:00+00:00",
                "2026-09-22T00:05:00+00:00",
                "2026-09-22T00:10:00+00:00",
                "2026-09-22T00:15:00+00:00",
            )
        )
        runtime = PlexApiRuntime(
            _config(tmp).plex_api,
            collector=collector,
            playback_state_path=Path(tmp) / "playback_session_starts.json",
            now_utc=lambda: next(times),
        )

        collector.sessions = (_session("s1"),)
        runtime.collect(now=100.0)
        assert runtime.payload()["playback_started_at"] == (
            "2026-09-22T00:00:00+00:00"
        )

        collector.sessions = (_session("s1"), _session("s2"))
        runtime.collect(now=110.0)
        assert runtime.payload()["playback_started_at"] == (
            "2026-09-22T00:00:00+00:00"
        )

        collector.sessions = (_session("s2"),)
        runtime.collect(now=120.0)
        assert runtime.payload()["playback_started_at"] == (
            "2026-09-22T00:05:00+00:00"
        )

        collector.sessions = ()
        runtime.collect(now=130.0)
        assert runtime.payload()["playback_started_at"] is None


def test_playback_started_at_survives_agent_runtime_recreation():
    with TemporaryDirectory() as tmp:
        state = Path(tmp) / "playback_session_starts.json"
        collector = FakeCollector()
        collector.sessions = (_session("same-session"),)

        first = PlexApiRuntime(
            _config(tmp).plex_api,
            collector=collector,
            playback_state_path=state,
            now_utc=lambda: "2026-09-22T00:00:00+00:00",
        )
        first.collect(now=100.0)
        assert state.is_file()

        second = PlexApiRuntime(
            _config(tmp).plex_api,
            collector=collector,
            playback_state_path=state,
            now_utc=lambda: "2026-09-22T00:20:00+00:00",
        )
        second.collect(now=200.0)
        assert second.payload()["playback_started_at"] == (
            "2026-09-22T00:00:00+00:00"
        )
