import sys

from app.config import AppConfig, GeneralConfig, MqttConfig
from app.identity import HostIdentity
import app.main as main_module


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
    )


def _identity():
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )


def test_uninstall_cleanup_cli_uses_config_identity_and_skips_runtime(monkeypatch):
    config = _config()
    identity = _identity()
    calls = []

    monkeypatch.setattr(sys, "argv", ["dh_pve_app", "--uninstall-mqtt-cleanup"])
    monkeypatch.setattr(main_module, "load_config", lambda path: config)
    monkeypatch.setattr(main_module, "resolve_identity", lambda general: identity)
    monkeypatch.setattr(
        main_module,
        "cleanup_mqtt",
        lambda actual_config, actual_identity: calls.append(
            (actual_config, actual_identity)
        )
        or True,
        raising=False,
    )
    monkeypatch.setattr(
        main_module,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("runtime must not start")
        ),
    )

    assert main_module.main() == 0
    assert calls == [(config, identity)]


def test_uninstall_cleanup_cli_returns_nonzero_on_mqtt_failure(monkeypatch):
    config = _config()
    identity = _identity()

    monkeypatch.setattr(sys, "argv", ["dh_pve_app", "--uninstall-mqtt-cleanup"])
    monkeypatch.setattr(main_module, "load_config", lambda path: config)
    monkeypatch.setattr(main_module, "resolve_identity", lambda general: identity)
    monkeypatch.setattr(
        main_module,
        "cleanup_mqtt",
        lambda actual_config, actual_identity: False,
        raising=False,
    )

    assert main_module.main() != 0
