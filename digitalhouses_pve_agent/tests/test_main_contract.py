from pathlib import Path

from app import main as main_module
from app.config import AppConfig, GeneralConfig, MqttConfig
from app.identity import HostIdentity
from app.runtime_problems import ProblemAwareRuntime

ROOT = Path(__file__).parents[1]


def _config():
    return AppConfig(
        general=GeneralConfig(instance_id="node_a", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(
            host="mqtt",
            port=1883,
            username="",
            password="",
            topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
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


def test_production_entrypoint_wires_all_phase1_collector_groups():
    text = (ROOT / "app" / "production.py").read_text()
    for name in ("host", "cpu", "memory", "storage", "smart", "gpu", "fans"):
        assert f'"{name}": self.{name}' in text


def test_guest_aware_mapping_wires_slow_disk_temperature_collector():
    text = (ROOT / "app" / "production_guest.py").read_text()
    mapping = text[text.index("def mapping(self):"):]
    assert '"disk_temperature": self.disk_temperature' in mapping


def test_main_uses_event_driven_runtime_without_state_heartbeat():
    text = (ROOT / "app" / "main.py").read_text()
    assert "runtime.process_events()" in text
    assert "runtime.tick(time.monotonic())" in text
    assert "heartbeat" not in text.casefold()


def test_runtime_scheduler_uses_frozen_collection_cadence(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "resolve_identity", lambda general: _identity())
    _bridge, runtime = main_module.build_runtime(_config(), state_dir=tmp_path)

    assert isinstance(runtime, ProblemAwareRuntime)
    assert runtime.scheduler.interval("cpu") == 10.0
    assert runtime.scheduler.interval("memory") == 10.0
    assert runtime.scheduler.interval("fans") == 10.0
    assert runtime.scheduler.interval("guests") == 60.0
    assert runtime.scheduler.interval("storage") == 60.0
    assert runtime.scheduler.interval("gpu") == 60.0
    assert runtime.scheduler.interval("disk_temperature") == 60.0
    assert runtime.scheduler.interval("smart") == 3600.0
    assert "host" not in runtime.scheduler.names()
    assert "topology" not in runtime.scheduler.names()
    assert "fast_poll_interval_seconds" not in runtime.setting_tasks
    assert "disk_poll_interval_seconds" not in runtime.setting_tasks


def test_main_wires_fast_manual_refresh_without_heavy_collectors(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "resolve_identity", lambda general: _identity())
    _bridge, runtime = main_module.build_runtime(_config(), state_dir=tmp_path)

    assert runtime.manual_refresh_collectors == (
        "topology",
        "guests",
        "host",
        "cpu",
        "memory",
        "storage",
        "fans",
    )
    assert "smart" not in runtime.manual_refresh_collectors
    assert "gpu" not in runtime.manual_refresh_collectors
    assert "disk_temperature" not in runtime.manual_refresh_collectors


def test_main_wires_shared_topology_shutdown_history_and_static_inventory():
    text = (ROOT / "app" / "main.py").read_text()
    assert "ShutdownAwareProductionCollectors" in text
    assert "ShutdownAwareTopologyManager" in text
    assert "ShutdownHistoryTracker" in text
    assert "build_shutdown_aware_pve_discovery_payload" in text
    assert "FAST_SECONDS = 10.0" in text
    assert "SLOW_SECONDS = 60.0" in text
    assert "HEALTH_SECONDS = 3600.0" in text


def test_main_wires_fixed_policy_reload_barrier():
    main_text = (ROOT / "app" / "main.py").read_text()
    unit_text = (ROOT / "systemd" / "digitalhouses_pve_agent.service").read_text()

    assert "FixedServiceReloadExecutor" in main_text
    assert "policy_reload_executor=FixedServiceReloadExecutor()" in main_text
    assert "signal.signal(signal.SIGHUP, reload_policy)" in main_text
    assert "ups_runtime.complete_policy_reload()" in main_text
    assert "ExecReload=/bin/kill -HUP $MAINPID" in unit_text


def test_guest_aware_full_collection_orders_topology_before_dependents():
    text = (ROOT / "app" / "production_guest.py").read_text()
    mapping = text[text.index("def mapping(self):"):]
    assert mapping.index('"topology": self.topology_inventory') < mapping.index('"smart": self.smart')
    assert mapping.index('"topology": self.topology_inventory') < mapping.index('"gpu": self.gpu')
    assert mapping.index('"guests": self.guests') < mapping.index('"smart": self.smart')
