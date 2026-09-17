import queue
import threading

from app.config import AppConfig, GeneralConfig, MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.machine_event_outbox import MachineEventOutbox
from app.main import build_ups_runtime
from app.state_store import StateStore
from app.ups_battery_events import UpsBatteryEventTracker
from app.ups_control import UpsCapabilities
from app.ups_group_runtime import AdaptiveUpsRuntime
from app.ups_nut import parse_upsc_output


class SemanticBridge:
    def __init__(self, trace):
        self.trace = trace
        self.ups_refresh_requested = threading.Event()
        self.ups_reconnect_requested = threading.Event()
        self.ups_test_quick_requested = threading.Event()
        self.ups_test_deep_requested = threading.Event()
        self.ups_test_stop_requested = threading.Event()
        self.ups_test_schedule_updates = queue.SimpleQueue()
        self.fail_event_once = False
        self.ups_topics = None

    def configure_ups(self, topics):
        self.ups_topics = topics

    def publish_ups_discovery(self, payload):
        return True

    def publish_ups_state_group(self, group, payload):
        self.trace.append(("group", group))
        return True

    def publish_ups_availability(self, online):
        return True

    def clear_legacy_ups_state(self):
        return True

    def publish_ups_problem_state(self, problem_id, active):
        self.trace.append(("problem_state", problem_id, active))
        return True

    def publish_ups_problem_aggregate(self, count):
        self.trace.append(("problem_aggregate", count))
        return True

    def publish_ups_problem_presentation(self, payload):
        self.trace.append(("problem_presentation",))
        return True

    def publish_ups_diagnostic_event(self, payload):
        self.trace.append(("event", payload["event_type"], payload))
        if self.fail_event_once:
            self.fail_event_once = False
            return False
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
        topic_prefix="DigitalHouses/Global/dh_pve_app",
        discovery_prefix="homeassistant",
        keepalive_seconds=60,
    )


def _ups_config():
    return UpsConfig(
        enabled=True,
        name="rackups",
        host="127.0.0.1",
        port=3493,
        poll_interval_seconds=5.0,
        command_timeout_seconds=3.0,
    )


def _app_config():
    return AppConfig(
        general=GeneralConfig(instance_id="", node_name="PVE", log_level="info"),
        mqtt=_mqtt(),
        ups=UpsConfig(enabled=False, poll_interval_seconds=5.0),
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


def _snapshot(status, charge):
    return parse_upsc_output(f"ups.status: {status}\nbattery.charge: {charge}\n")


def _runtime(tmp_path, current, clock, trace, reads):
    bridge = SemanticBridge(trace)

    def reader(config):
        trace.append(("read",))
        reads["count"] += 1
        return current["snapshot"]

    outbox = MachineEventOutbox(StateStore(tmp_path / "machine-events.json"))
    battery = UpsBatteryEventTracker(StateStore(tmp_path / "battery-events.json"))
    runtime = AdaptiveUpsRuntime(
        config=_ups_config(),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.5.0",
        state_store=StateStore(tmp_path / "ups.json"),
        machine_event_outbox=outbox,
        battery_event_tracker=battery,
        now_iso=lambda: clock["iso"],
        now_monotonic=lambda: clock["mono"],
        reader=reader,
        capability_reader=_capabilities,
        shutdown_policy_reader=lambda: None,
    )
    return bridge, runtime, outbox


def _index(trace, kind, detail=None):
    for index, item in enumerate(trace):
        if item[0] != kind:
            continue
        if detail is None or (len(item) > 1 and item[1] == detail):
            return index
    raise AssertionError(f"missing trace item: {kind} {detail}: {trace}")


def test_semantic_events_follow_retained_state_and_problem_publication(tmp_path):
    current = {"snapshot": _snapshot("OL", 100)}
    clock = {"iso": "2026-09-17T14:00:00+05:00", "mono": 0.0}
    trace = []
    reads = {"count": 0}
    bridge, runtime, outbox = _runtime(tmp_path, current, clock, trace, reads)

    assert runtime.startup() is True
    trace.clear()

    current["snapshot"] = _snapshot("OB DISCHRG", 94)
    clock.update(iso="2026-09-17T14:00:10+05:00", mono=10.0)
    assert runtime.tick(clock["mono"]) is True

    status_event = _index(trace, "event", "ups_status_changed")
    assert _index(trace, "group", "status") < status_event
    assert _index(trace, "problem_state", "on_battery") < status_event
    assert _index(trace, "problem_aggregate") < status_event
    assert outbox.pending() == ()

    trace.clear()
    current["snapshot"] = _snapshot("OB DISCHRG", 87)
    clock.update(iso="2026-09-17T14:00:20+05:00", mono=20.0)
    assert runtime.tick(clock["mono"]) is True

    milestone = _index(trace, "event", "battery_discharge_level_crossed")
    assert _index(trace, "group", "battery") < milestone
    event_payload = trace[milestone][2]
    assert event_payload["crossed_thresholds"] == [90]
    assert outbox.pending() == ()


def test_failed_semantic_event_is_retried_before_next_nut_read_without_duplicate(tmp_path):
    current = {"snapshot": _snapshot("OB DISCHRG", 94)}
    clock = {"iso": "2026-09-17T14:00:00+05:00", "mono": 0.0}
    trace = []
    reads = {"count": 0}
    bridge, runtime, outbox = _runtime(tmp_path, current, clock, trace, reads)

    assert runtime.startup() is True
    trace.clear()

    current["snapshot"] = _snapshot("OB DISCHRG", 87)
    bridge.fail_event_once = True
    clock.update(iso="2026-09-17T14:00:10+05:00", mono=10.0)
    assert runtime.tick(clock["mono"]) is False
    assert [item.payload["event_type"] for item in outbox.pending()] == [
        "battery_discharge_level_crossed"
    ]

    reads_before_retry = reads["count"]
    trace.clear()
    clock.update(iso="2026-09-17T14:00:20+05:00", mono=20.0)
    assert runtime.tick(clock["mono"]) is True

    assert trace[0][0:2] == ("event", "battery_discharge_level_crossed")
    assert _index(trace, "event", "battery_discharge_level_crossed") < _index(trace, "read")
    assert reads["count"] == reads_before_retry + 1
    assert sum(
        1
        for item in trace
        if item[0:2] == ("event", "battery_discharge_level_crossed")
    ) == 1
    assert outbox.pending() == ()


def test_build_ups_runtime_wires_dedicated_semantic_state_stores(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.resolve_identity", lambda general: _identity())
    bridge = SemanticBridge([])

    runtime = build_ups_runtime(
        _app_config(),
        bridge,
        selected_name="rackups",
        state_dir=tmp_path,
    )

    assert runtime is not None
    assert runtime.machine_event_outbox.state_store.path == (
        tmp_path / "ups_machine_event_outbox.json"
    )
    assert runtime.battery_event_tracker.state_store.path == (
        tmp_path / "ups_battery_events.json"
    )
