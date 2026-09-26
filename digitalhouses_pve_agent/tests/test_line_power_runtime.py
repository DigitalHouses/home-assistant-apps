from __future__ import annotations

import queue
import threading
from datetime import datetime

from app.config import AppConfig, GeneralConfig, MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.line_power_statistics import LinePowerStatisticsTracker
from app.main import build_ups_runtime
from app.shutdown_integration import ShutdownAwareUpsRuntime
from app.state_store import StateStore
from app.ups_control import UpsCapabilities
from app.ups_nut import parse_upsc_output


class GroupBridge:
    def __init__(self):
        self.ups_refresh_requested = threading.Event()
        self.ups_reconnect_requested = threading.Event()
        self.ups_test_quick_requested = threading.Event()
        self.ups_test_deep_requested = threading.Event()
        self.ups_test_stop_requested = threading.Event()
        self.ups_test_schedule_updates = queue.SimpleQueue()
        self.groups = []
        self.discovery = []
        self.availability = []
        self.legacy_state_cleanup = 0

    def configure_ups(self, topics):
        self.ups_topics = topics

    def publish_ups_discovery(self, payload):
        self.discovery.append(payload)
        return True

    def publish_ups_state_group(self, group, payload):
        self.groups.append((group, payload))
        return True

    def publish_ups_availability(self, online):
        self.availability.append(online)
        return True

    def clear_legacy_ups_state(self):
        self.legacy_state_cleanup += 1
        return True


class ShutdownTracker:
    def __init__(self):
        self.observed = []

    def observe_ups(self, snapshot):
        self.observed.append(snapshot.status_raw)

    def payload(self):
        return {"history": [], "previous_shutdown": None}


def _identity():
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )


def _mqtt():
    return MqttConfig(
        host="mqtt",
        port=1883,
        username="",
        password="",
        topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
        discovery_prefix="homeassistant",
        keepalive_seconds=60,
    )


def _ups_config():
    return UpsConfig(
        enabled=True,
        name="ups",
        host="127.0.0.1",
        port=3493,
        poll_interval_seconds=10.0,
        command_timeout_seconds=3.0,
    )


def _capabilities(config):
    return UpsCapabilities(
        commands=(),
        battery_tests=(),
        beeper_control=False,
        load_control=False,
        shutdown_control=False,
        supported_features=(),
    )


def test_shutdown_runtime_feeds_tracker_and_publishes_monthly_group(tmp_path):
    clock = {
        "iso": "2026-09-17T03:00:00+05:00",
        "mono": 0.0,
    }
    current = {
        "snapshot": parse_upsc_output("ups.status: OL\n")
    }
    bridge = GroupBridge()
    tracker = LinePowerStatisticsTracker(
        StateStore(tmp_path / "line_power_statistics.json"),
        now_local=lambda: datetime.fromisoformat(clock["iso"]),
    )
    runtime = ShutdownAwareUpsRuntime(
        config=_ups_config(),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.3.0",
        state_store=StateStore(tmp_path / "ups_runtime.json"),
        now_iso=lambda: clock["iso"],
        now_local=lambda: datetime.fromisoformat(clock["iso"]),
        now_monotonic=lambda: clock["mono"],
        reader=lambda config: current["snapshot"],
        capability_reader=_capabilities,
        shutdown_policy_reader=lambda: None,
        shutdown_history_tracker=ShutdownTracker(),
        line_power_statistics_tracker=tracker,
    )

    assert runtime.startup() is True
    grouped = dict(bridge.groups)
    assert grouped["line_power_statistics"]["state"] == "online"
    assert grouped["line_power_statistics"]["partial_month"] is True
    assert grouped["line_power_statistics"]["tracking_since"] == clock["iso"]

    bridge.groups.clear()
    current["snapshot"] = parse_upsc_output("ups.status: OB DISCHRG\n")
    clock["mono"] = 10.0
    clock["iso"] = "2026-09-17T03:00:10+05:00"
    assert runtime.tick(clock["mono"]) is True

    grouped = dict(bridge.groups)
    assert grouped["line_power_statistics"]["state"] == "offline"
    assert grouped["line_power_statistics"]["outages_month"] == 1
    assert grouped["line_power_statistics"]["online_seconds"] == 10

    bridge.groups.clear()
    clock["mono"] = 20.0
    clock["iso"] = "2026-09-17T03:00:20+05:00"
    assert runtime.tick(clock["mono"]) is True
    grouped = dict(bridge.groups)
    assert grouped["line_power_statistics"]["offline_seconds"] == 10


def test_nut_failure_transitions_line_power_to_unknown_not_offline(tmp_path):
    clock = {
        "iso": "2026-09-17T03:00:00+05:00",
        "mono": 0.0,
    }
    current = {"fail": False}

    def reader(config):
        if current["fail"]:
            raise RuntimeError("NUT unavailable")
        return parse_upsc_output("ups.status: OL\n")

    bridge = GroupBridge()
    tracker = LinePowerStatisticsTracker(
        StateStore(tmp_path / "line_power_statistics.json"),
        now_local=lambda: datetime.fromisoformat(clock["iso"]),
    )
    runtime = ShutdownAwareUpsRuntime(
        config=_ups_config(),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.3.0",
        state_store=StateStore(tmp_path / "ups_runtime.json"),
        now_iso=lambda: clock["iso"],
        now_local=lambda: datetime.fromisoformat(clock["iso"]),
        now_monotonic=lambda: clock["mono"],
        reader=reader,
        capability_reader=_capabilities,
        shutdown_policy_reader=lambda: None,
        shutdown_history_tracker=ShutdownTracker(),
        line_power_statistics_tracker=tracker,
    )
    assert runtime.startup() is True
    bridge.groups.clear()

    current["fail"] = True
    clock["mono"] = 10.0
    clock["iso"] = "2026-09-17T03:00:10+05:00"
    assert runtime.tick(clock["mono"]) is False

    grouped = dict(bridge.groups)
    assert grouped["line_power_statistics"]["state"] == "unknown"
    assert grouped["line_power_statistics"]["offline_seconds"] == 0
    assert grouped["line_power_statistics"]["outages_month"] == 0


def test_build_ups_runtime_uses_dedicated_line_power_store(tmp_path, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "resolve_identity", lambda general: _identity())
    config = AppConfig(
        general=GeneralConfig(instance_id="node_a", node_name="PVE", log_level="info"),
        mqtt=_mqtt(),
        ups=_ups_config(),
    )
    bridge = GroupBridge()

    runtime = build_ups_runtime(
        config,
        bridge,
        selected_name="ups",
        state_dir=tmp_path,
        shutdown_history_tracker=ShutdownTracker(),
    )

    assert runtime is not None
    assert runtime.line_power_statistics_tracker.store.path == (
        tmp_path / "line_power_statistics.json"
    )
