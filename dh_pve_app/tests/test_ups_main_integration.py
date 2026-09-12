from pathlib import Path

from app.config import AppConfig, GeneralConfig, MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.main import build_ups_runtime


class Bridge:
    def __init__(self):
        self.ups_topics = None

    def configure_ups(self, topics):
        self.ups_topics = topics


def _config(enabled: bool):
    return AppConfig(
        general=GeneralConfig(instance_id="", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(
            host="mqtt",
            port=1883,
            username="",
            password="",
            topic_prefix="DigitalHouses/Global/dh_pve_app",
            discovery_prefix="homeassistant",
            keepalive_seconds=60,
        ),
        ups=UpsConfig(enabled=enabled, poll_interval_seconds=5.0),
    )


def test_ups_disabled_builds_no_aux_runtime(tmp_path: Path):
    bridge = Bridge()
    assert build_ups_runtime(_config(False), bridge, state_dir=tmp_path) is None
    assert bridge.ups_topics is None


def test_ups_enabled_builds_aux_runtime_and_configures_topics(tmp_path: Path, monkeypatch):
    identity = HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )
    monkeypatch.setattr("app.main.resolve_identity", lambda general: identity)
    bridge = Bridge()

    runtime = build_ups_runtime(_config(True), bridge, state_dir=tmp_path)

    assert runtime is not None
    assert runtime.config.enabled is True
    assert bridge.ups_topics is not None
    assert bridge.ups_topics.device_id == "dh_ups_node_a"
    assert bridge.ups_topics.state.endswith("/node_a/ups/state")


def test_main_orchestration_keeps_ups_startup_independent_from_pve():
    text = (Path(__file__).parents[1] / "app" / "main.py").read_text(encoding="utf-8")

    assert "ups_runtime = build_ups_runtime" in text
    assert "initialized = runtime.startup()" in text
    assert "initialized = ups_runtime.startup()" not in text
    assert "ups_runtime.process_events()" in text
    assert "ups_runtime.tick(time.monotonic())" in text
