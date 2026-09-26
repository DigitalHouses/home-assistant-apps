from pathlib import Path

from app.config import AppConfig, GeneralConfig, MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.main import build_ups_runtime
from app.ups_shutdown_budget import ShutdownBudgetInputs, calculate_shutdown_budget


class Bridge:
    def __init__(self):
        self.ups_topics = None

    def configure_ups(self, topics):
        self.ups_topics = topics


class HistoryTracker:
    def __init__(self):
        self.history = [{"shutdown_clean": True}]
        self.fingerprints = []
        self.commits = []

    def payload(self):
        return {
            "current_boot": None,
            "previous_shutdown": None,
            "history": list(self.history),
            "history_count": len(self.history),
        }

    def observe_ups(self, snapshot):
        return None

    def record_shutdown_budget_fingerprint(self, fingerprint):
        self.fingerprints.append(fingerprint)

    def record_software_shutdown_commit(self, reason, snapshot):
        self.commits.append(reason)


def _config():
    return AppConfig(
        general=GeneralConfig(instance_id="", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(
            host="mqtt",
            port=1883,
            username="",
            password="",
            topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
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
    assert bridge.ups_topics.device_id == "dh_pve_agent_ups_node_a"
    assert bridge.ups_topics.state.endswith("/node_a/ups/state")


def test_selected_ups_wires_cheap_budget_reader_and_fixed_shutdown_executor(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr("app.main.resolve_identity", lambda general: _identity())
    budget_calls = []
    shutdown_calls = []
    tracker = HistoryTracker()
    budget = calculate_shutdown_budget(
        ShutdownBudgetInputs(280, None, 120, True, 5, None, 90)
    )

    def fake_budget(config, *, node_name, history):
        budget_calls.append((config.name, node_name, history))
        return budget

    def fake_shutdown(reason):
        shutdown_calls.append(reason)

    monkeypatch.setattr("app.main.read_shutdown_budget", fake_budget, raising=False)
    monkeypatch.setattr("app.main.execute_fixed_ups_shutdown", fake_shutdown, raising=False)
    bridge = Bridge()

    runtime = build_ups_runtime(
        _config(),
        bridge,
        selected_name="rackups",
        state_dir=tmp_path,
        shutdown_history_tracker=tracker,
    )

    assert runtime is not None
    assert runtime.shutdown_budget_reader is not None
    assert runtime.software_shutdown_controller is not None
    assert runtime._current_shutdown_budget() == budget
    assert budget_calls == [("rackups", "pve", tracker.history)]
    runtime.software_shutdown_controller.executor("runtime_guard")
    assert shutdown_calls == ["runtime_guard"]


def test_main_orchestration_processes_scan_before_optional_ups_runtime():
    text = (Path(__file__).parents[1] / "app" / "main.py").read_text(encoding="utf-8")

    assert "UpsScanner" in text
    assert "ups_scan_requested" in text
    assert "publish_ups_scan_state" in text
    assert "scanner.selected_name()" in text
    assert "outcome.selection_changed" in text
    assert "ups_runtime = build_ups_runtime" in text
    assert "bridge.clear_legacy_ups_discovery()" in text
    assert "initialized = ups_runtime.startup()" not in text


def test_production_ups_runtime_does_not_use_legacy_heavy_policy_facts_reader():
    text = (Path(__file__).parents[1] / "app" / "main.py").read_text(encoding="utf-8")

    assert "read_policy_safety_facts" not in text
