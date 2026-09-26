import queue
import threading

from app.config import MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.state_store import StateStore
from app.ups_control import UpsCapabilities
from app.ups_group_runtime import AdaptiveUpsRuntime
from app.ups_nut import parse_upsc_output


class GroupBridge:
    def __init__(self):
        self.ups_refresh_requested = threading.Event()
        self.ups_reconnect_requested = threading.Event()
        self.ups_test_quick_requested = threading.Event()
        self.ups_test_deep_requested = threading.Event()
        self.ups_test_stop_requested = threading.Event()
        self.ups_test_schedule_updates = queue.SimpleQueue()
        self.discovery = []
        self.groups = []
        self.states = []
        self.availability = []
        self.legacy_state_cleanup = 0

    def publish_ups_discovery(self, payload):
        self.discovery.append(payload)
        return True

    def publish_ups_state_group(self, group, payload):
        self.groups.append((group, payload))
        return True

    def publish_ups_state(self, payload):
        self.states.append(payload)
        return True

    def publish_ups_availability(self, online):
        self.availability.append(online)
        return True

    def clear_legacy_ups_state(self):
        self.legacy_state_cleanup += 1
        return True


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


def _config():
    return UpsConfig(
        enabled=True,
        name="ups",
        host="127.0.0.1",
        port=3493,
        poll_interval_seconds=5.0,
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


def _runtime(tmp_path, reader, clock):
    bridge = GroupBridge()
    runtime = AdaptiveUpsRuntime(
        config=_config(),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.2.0",
        state_store=StateStore(tmp_path / "ups.json"),
        now_iso=lambda: clock["iso"],
        now_monotonic=lambda: clock["mono"],
        reader=reader,
        capability_reader=_capabilities,
        shutdown_policy_reader=lambda: None,
    )
    return bridge, runtime


def test_group_capable_startup_uses_only_group_transport(tmp_path):
    snapshot = parse_upsc_output(
        "device.model: UT2200E\nups.status: OL\n"
        "battery.charge: 100\nbattery.runtime: 2160\nups.load: 5\n"
    )
    clock = {"iso": "2026-09-14T20:00:00+05:00", "mono": 0.0}
    bridge, runtime = _runtime(tmp_path, lambda config: snapshot, clock)

    assert runtime.startup() is True

    assert bridge.states == []
    assert bridge.legacy_state_cleanup == 1
    grouped = dict(bridge.groups)
    assert set(grouped) == {
        "telemetry",
        "status",
        "config",
        "tests",
        "diagnostics",
    }
    diagnostics = grouped["diagnostics"]
    assert diagnostics["app_profile"]["state"] == "normal"
    assert diagnostics["last_publication"] == {
        "timestamp": "2026-09-14T20:00:00+05:00",
        "group": "tests",
        "reason": "startup",
        "profile": "normal",
        "group_count": 4,
    }


def test_unchanged_online_poll_does_not_refresh_group_states(tmp_path):
    snapshot = parse_upsc_output("ups.status: OL\nbattery.runtime: 2160\nups.load: 5\n")
    clock = {"iso": "2026-09-14T20:00:00+05:00", "mono": 0.0}
    bridge, runtime = _runtime(tmp_path, lambda config: snapshot, clock)
    runtime.startup()
    bridge.groups.clear()

    clock["mono"] = 10.0
    clock["iso"] = "2026-09-14T20:00:10+05:00"
    assert runtime.tick(clock["mono"]) is True

    assert bridge.groups == []


def test_on_battery_transition_publishes_status_telemetry_and_diagnostics(tmp_path):
    current = {"snapshot": parse_upsc_output("ups.status: OL\nbattery.runtime: 2160\nups.load: 5\n")}
    clock = {"iso": "2026-09-14T20:00:00+05:00", "mono": 0.0}
    bridge, runtime = _runtime(tmp_path, lambda config: current["snapshot"], clock)
    runtime.startup()
    bridge.groups.clear()

    current["snapshot"] = parse_upsc_output(
        "ups.status: OB DISCHRG\nbattery.runtime: 2130\nups.load: 5\n"
    )
    clock["mono"] = 10.0
    clock["iso"] = "2026-09-14T20:00:10+05:00"
    runtime.tick(clock["mono"])

    grouped = dict(bridge.groups)
    assert set(grouped) == {"status", "telemetry", "diagnostics"}
    assert grouped["diagnostics"]["app_profile"]["state"] == "detail"
    assert grouped["diagnostics"]["last_publication"]["group"] == "status"
    assert grouped["diagnostics"]["last_publication"]["group_count"] == 2
    assert bridge.states == []


def test_manual_refresh_publishes_all_groups_and_updates_last_refresh(tmp_path):
    snapshot = parse_upsc_output("ups.status: OL\nbattery.charge: 100\nups.load: 5\n")
    clock = {"iso": "2026-09-14T20:00:00+05:00", "mono": 0.0}
    bridge, runtime = _runtime(tmp_path, lambda config: snapshot, clock)
    runtime.startup()
    bridge.groups.clear()

    clock["mono"] = 5.0
    clock["iso"] = "2026-09-14T20:00:05+05:00"
    assert runtime.manual_refresh() is True

    grouped = dict(bridge.groups)
    assert set(grouped) == {"telemetry", "status", "config", "tests", "diagnostics"}
    assert grouped["diagnostics"]["last_refresh"] == "2026-09-14T20:00:05+05:00"
    assert grouped["diagnostics"]["last_publication"]["reason"] == "manual_refresh"
    assert grouped["diagnostics"]["last_publication"]["group_count"] == 4


def test_reconnect_replays_group_cache_without_new_nut_read(tmp_path):
    calls = {"count": 0}
    snapshot = parse_upsc_output("ups.status: OL\nbattery.charge: 100\n")

    def reader(config):
        calls["count"] += 1
        return snapshot

    clock = {"iso": "2026-09-14T20:00:00+05:00", "mono": 0.0}
    bridge, runtime = _runtime(tmp_path, reader, clock)
    runtime.startup()
    before = calls["count"]
    cached = {group for group, _payload in bridge.groups}
    bridge.groups.clear()
    bridge.states.clear()

    assert runtime.republish_after_reconnect() is True

    assert calls["count"] == before
    assert {group for group, _payload in bridge.groups} == cached
    assert bridge.states == []
