import queue
import threading

from app.config import MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.machine_event_outbox import MachineEventOutbox
from app.state_store import StateStore
from app.ups_control import UpsCapabilities
from app.ups_group_runtime import AdaptiveUpsRuntime
from app.ups_nut import parse_upsc_output


class Bridge:
    def __init__(self):
        self.ups_refresh_requested = threading.Event()
        self.ups_reconnect_requested = threading.Event()
        self.ups_test_quick_requested = threading.Event()
        self.ups_test_deep_requested = threading.Event()
        self.ups_test_stop_requested = threading.Event()
        self.ups_test_schedule_updates = queue.SimpleQueue()
        self.problem_calls = []

    def publish_ups_discovery(self, payload):
        return True

    def publish_ups_state_group(self, group, payload):
        return True

    def publish_ups_availability(self, online):
        return True

    def clear_legacy_ups_state(self):
        return True

    def publish_ups_problem_state(self, problem_id, active):
        self.problem_calls.append(("state", problem_id, active))
        return True

    def publish_ups_problem_aggregate(self, count):
        self.problem_calls.append(("aggregate", count))
        return True

    def publish_ups_problem_presentation(self, payload):
        self.problem_calls.append(("presentation", payload))
        return True

    def publish_ups_diagnostic_event(self, payload):
        self.problem_calls.append(("event", payload))
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


def _config():
    return UpsConfig(
        enabled=True,
        name="rackups",
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


def test_on_battery_transition_updates_retained_problem_but_emits_only_status_event(tmp_path):
    current = {"snapshot": parse_upsc_output("ups.status: OL\nbattery.charge: 100\n")}
    clock = {"iso": "2026-09-17T12:00:00+05:00", "mono": 0.0}
    bridge = Bridge()

    def reader(config):
        return current["snapshot"]

    runtime = AdaptiveUpsRuntime(
        config=_config(),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.5.0",
        state_store=StateStore(tmp_path / "ups.json"),
        machine_event_outbox=MachineEventOutbox(
            StateStore(tmp_path / "machine-events.json")
        ),
        now_iso=lambda: clock["iso"],
        now_monotonic=lambda: clock["mono"],
        reader=reader,
        capability_reader=_capabilities,
        shutdown_policy_reader=lambda: None,
    )

    assert runtime.startup() is True
    bridge.problem_calls.clear()

    current["snapshot"] = parse_upsc_output(
        "ups.status: OB DISCHRG\nbattery.charge: 90\n"
    )
    clock.update(iso="2026-09-17T12:00:10+05:00", mono=10.0)

    assert runtime.tick(clock["mono"]) is True

    assert ("state", "on_battery", True) in bridge.problem_calls
    events = [call[1] for call in bridge.problem_calls if call[0] == "event"]
    assert [event["event_type"] for event in events] == ["ups_status_changed"]
    assert events[0]["previous_status"] == ["online"]
    assert events[0]["current_status"] == ["on_battery"]
    assert not any(
        event.get("event_type") == "problem_started"
        and event.get("problem_id") == "on_battery"
        for event in events
    )
