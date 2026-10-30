from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import load_config
from app.discovery import build_discovery_payload, build_topics, state_group_topic
from app.models import ActivityState, BuildInfo, CpuGroupMetrics, CpuMetrics, MonitorSnapshot
from app.plex_api import PlaybackSession, build_plex_api_payload
from app.presentation_runtime import PlexPublicationRuntime


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = (ROOT / "examples/lovelace/plex-dashboard.yaml").read_text(encoding="utf-8")
INSTALLER = (ROOT / "install.sh").read_text(encoding="utf-8")


def config():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "app.conf"
        path.write_text("[mqtt]\nhost = mqtt\n", encoding="utf-8")
        return load_config(path)

def snapshot():
    return MonitorSnapshot(
        collected_at="2026-09-21T15:00:00+00:00",
        activity=ActivityState(
            plex_server_running=True,
            scanner_running=False,
            credits_detection=False,
            intro_detection=False,
            thumbnail_generation=False,
            transcoder_running=True,
            activity="transcoding",
            scanner_actions=(),
            current_item="movie.mkv",
        ),
        cpu=CpuMetrics(
            CpuGroupMetrics(80.0, 60.0, 90.0),
            CpuGroupMetrics(0.0, 0.0, 0.0),
            CpuGroupMetrics(75.0, 55.0, 85.0),
        ),
        process_count=4,
        collector_status="ok",
        last_refresh=None,
    )


class FakeBridge:
    def __init__(self):
        self.groups = []

    def publish_state_group(self, group, payload):
        self.groups.append((group, payload))
        return True


def test_discovery_exposes_standalone_gpu_and_server_boot_entities():
    cfg = config()
    topics = build_topics(cfg)
    components = build_discovery_payload(
        cfg,
        BuildInfo("0.4.0", "digitalhouses_plex_agent-v0.4.0", "abcdef"),
    )["components"]

    gpu = state_group_topic(topics, "gpu")
    expected = {
        "gpu_video": ("sensor.dh_plex_agent_gpu_video", "%"),
        "gpu_render": ("sensor.dh_plex_agent_gpu_render", "%"),
        "gpu_video_enhance": ("sensor.dh_plex_agent_gpu_video_enhance", "%"),
        "gpu_frequency": ("sensor.dh_plex_agent_gpu_frequency", "MHz"),
        "gpu_temperature": ("sensor.dh_plex_agent_gpu_temperature", "°C"),
        "gpu_rc6": ("sensor.dh_plex_agent_gpu_rc6", "%"),
        "gpu_status": ("sensor.dh_plex_agent_gpu_status", None),
        "gpu_driver_status": ("sensor.dh_plex_agent_gpu_driver_status", None),
    }
    for key, (entity_id, unit) in expected.items():
        assert components[key]["default_entity_id"] == entity_id
        assert components[key]["state_topic"] == gpu
        if unit is not None:
            assert components[key]["unit_of_measurement"] == unit

    assert components["last_boot"]["default_entity_id"] == "sensor.dh_plex_agent_last_boot"
    assert components["last_boot"]["state_topic"] == state_group_topic(topics, "diagnostics")
    assert components["last_boot"]["device_class"] == "timestamp"

    assert components["hardware_transcode_active"]["default_entity_id"] == (
        "binary_sensor.dh_plex_agent_hardware_transcode_active"
    )
    assert components["hardware_transcode_active"]["state_topic"] == state_group_topic(
        topics, "playback"
    )


def test_plex_api_exposes_aggregate_hardware_transcode_state():
    sessions = (
        PlaybackSession(
            session_id="1",
            content_type="video",
            media_type="movie",
            title="Movie",
            mode="Transcode",
            hardware_transcode=True,
        ),
    )

    payload = build_plex_api_payload(sessions, (), "ok")

    assert payload["hardware_transcode_active"] is True


def test_runtime_publishes_gpu_group_and_server_boot_timestamp():
    bridge = FakeBridge()
    values = iter([100.0, 100.0])
    runtime = PlexPublicationRuntime(
        bridge=bridge,
        build=BuildInfo("0.4.0", "digitalhouses_plex_agent-v0.4.0", "abcdef"),
        source_interval_seconds=10.0,
        agent_started_at="2026-09-21T00:00:00+00:00",
        now_monotonic=lambda: next(values),
        server_boot_time="2026-09-20T01:05:32+00:00",
    )
    api = {
        "plex_api_status": "ok",
        "playback_count": 0,
        "playback_sessions_state": "0 sessions",
        "playback_active": False,
        "video_playback_count": 0,
        "audio_playback_count": 0,
        "video_playback_active": False,
        "audio_playback_active": False,
        "hardware_transcode_active": False,
        "playback_sessions": [],
        "library_count": 0,
        "libraries": [],
        "libraries_by_id": {},
    }
    gpu = {
        "supported": True,
        "available": True,
        "status": "ok",
        "source": "intel_gpu_top",
        "video_busy_percent": 16.4,
        "render_busy_percent": 77.7,
        "video_enhance_busy_percent": 0.0,
        "frequency_mhz": 706.7,
        "rc6_percent": 2.3,
        "temperature_c": None,
    }

    assert runtime.publish_snapshot(snapshot(), api, gpu_payload=gpu, force=True) is True

    published = dict(bridge.groups)
    assert published["gpu"]["video_busy_percent"] == 16.4
    assert published["gpu"]["render_busy_percent"] == 77.7
    assert published["diagnostics"]["server_boot_time"] == "2026-09-20T01:05:32+00:00"


def test_deployed_dashboard_shows_gpu_load_history_and_agent_uptime():
    # The operator's deployed dashboard selects active GPU utilization rather
    # than the full set of available diagnostic entities. Discovery tests above
    # still enforce the complete standalone GPU and server-boot contract.
    for entity_id in (
        "sensor.dh_plex_agent_gpu_video",
        "sensor.dh_plex_agent_gpu_render",
        "sensor.dh_plex_agent_gpu_video_enhance",
        "sensor.dh_plex_agent_cpu",
        "sensor.dh_plex_agent_transcoder_cpu",
        "sensor.dh_plex_agent_uptime",
        "binary_sensor.dh_plex_agent_server_running",
    ):
        assert entity_id in DASHBOARD

    assert "hours_to_show: 3" in DASHBOARD
    assert "type: trend-graph" in DASHBOARD
    assert "sensor.dh_app_pve_" not in DASHBOARD


def test_installer_prepares_optional_intel_gpu_telemetry():
    assert "intel-gpu-tools" in INSTALLER
    assert "render" in INSTALLER
    assert "video" in INSTALLER


def test_driver_state_published_in_existing_gpu_group():
    from app.presentation_plex import PlexPresentationRouter

    router = PlexPresentationRouter(source_interval_seconds=10.0)
    source = {
        "supported": True, "available": False, "status": "error",
        "driver_status": "bound", "driver_name": "i915",
        "pci_address": "0000:01:00.0",
    }
    api = {
        "plex_api_status": "ok",
        "playback_active": False,
        "playback_count": 0,
        "playback_sessions": [],
    }
    published = router.route(snapshot(), api, source, now=0, force=True)
    gpu = {p.group: p.payload for p in published}["gpu"]
    assert gpu["driver_status"] == "bound"
    assert gpu["driver_name"] == "i915"
    assert gpu["status"] == "error"
