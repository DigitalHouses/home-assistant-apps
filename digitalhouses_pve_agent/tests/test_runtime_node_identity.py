from __future__ import annotations

from app.config import AppConfig, GeneralConfig, MqttConfig
from app.identity import HostIdentity
from app import main


def test_build_runtime_uses_hostname_for_pve_cache_node(monkeypatch, tmp_path):
    identity = HostIdentity(
        machine_id="a" * 32,
        instance_id="a" * 32,
        hostname="pve",
        node_name="PVE",
    )
    monkeypatch.setattr(main, "resolve_identity", lambda _config: identity)

    observed: dict[str, str] = {}

    class FakeProduction:
        def __init__(self, *args, node_name: str, **kwargs):
            observed["node_name"] = node_name

        def mapping(self):
            return {}

    monkeypatch.setattr(main, "ShutdownAwareProductionCollectors", FakeProduction)
    monkeypatch.setattr(main, "MqttBridge", lambda *args, **kwargs: object())
    monkeypatch.setattr(main, "ProblemAwareRuntime", lambda **kwargs: object())
    monkeypatch.setattr(
        main,
        "build_shutdown_aware_pve_discovery_payload",
        lambda *args, **kwargs: {"components": {}},
    )

    config = AppConfig(
        general=GeneralConfig(instance_id="", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(
            host="127.0.0.1",
            port=1883,
            username="",
            password="",
            topic_prefix="DigitalHouses/Global/dh_pve_app",
            discovery_prefix="homeassistant",
            keepalive_seconds=60,
        ),
    )

    main.build_runtime(config, state_dir=tmp_path)

    assert observed["node_name"] == "pve"
