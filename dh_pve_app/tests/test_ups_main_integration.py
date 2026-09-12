from pathlib import Path

from app.config import AppConfig, GeneralConfig, MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.main import build_ups_runtime


class Bridge:
    def __init__(self):
        self.ups_topics = None

    def configure_ups(self, topics):
        self.ups_topics = topics


def _config():
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
        ups=UpsConfig(enabled=False, poll_interval_seconds=5.0),
    )


def _identity():
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )


def test_no_selected_ups_builds_no_aux_runtime(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.main.resolve_identity", lambda general: _identity())
    bridge = Bridge()

    runtime = build_ups_runtime(_config(), bridge, selected_name=None, state_dir=tmp_path)

    assert runtime is None
    assert bridge.ups_topics is None


def test_selected_ups_builds_aux_runtime_and_configures_scoped_topics(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.main.resolve_identity", lambda general: _identity())
    bridge = Bridge()

    runtime = build_ups_runtime(_config(), bridge, selected_name="rackups", state_dir=tmp_path)

    assert runtime is not None
    assert runtime.config.name == "rackups"
    assert bridge.ups_topics is not None
    assert bridge.ups_topics.device_id == "dh_pve_ups_node_a"
    assert bridge.ups_topics.state.endswith("/node_a/ups/state")


def test_main_orchestration_processes_scan_before_optional_ups_runtime():
    text = (Path(__file__).parents[1] / "app" / "main.py").read_text(encoding="utf-8")

    assert "UpsScanner" in text
    assert "ups_scan_requested" in text
    assert "publish_ups_scan_state" in text
    assert "scanner.selected_name()" in text
    assert "outcome.selection_changed" in text
    assert "ups_runtime = build_ups_runtime" in text
    assert "initialized = ups_runtime.startup()" not in text
