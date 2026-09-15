from pathlib import Path

from app.config import AppConfig, GeneralConfig, MqttConfig, UpsConfig
from app.identity import HostIdentity
import app.main as main_module


class Bridge:
    def configure_ups(self, topics):
        self.topics = topics


class Tracker:
    def payload(self):
        return {"history": []}


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
        ups=UpsConfig(enabled=True, name="ups"),
    )


def test_build_ups_runtime_uses_technical_hostname_for_pve_rrd_budget(tmp_path: Path, monkeypatch):
    identity = HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )
    monkeypatch.setattr(main_module, "resolve_identity", lambda general: identity)

    calls = []

    def fake_budget(config, *, node_name, history):
        calls.append((node_name, history))
        return object()

    monkeypatch.setattr(main_module, "read_shutdown_budget", fake_budget)
    monkeypatch.setattr(main_module, "read_shutdown_policy", lambda **kwargs: object())

    runtime = main_module.build_ups_runtime(
        _config(),
        Bridge(),
        selected_name="ups",
        state_dir=tmp_path,
        shutdown_history_tracker=Tracker(),
    )

    assert runtime is not None
    runtime.shutdown_budget_reader()
    assert calls == [("pve", [])]
