import queue
import threading

from app.config import MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.state_store import StateStore
from app.ups_control import UpsCapabilities
from app.ups_group_runtime import AdaptiveUpsRuntime
from app.ups_nut import parse_upsc_output


PROBLEM_IDS = {
    "nut_unavailable",
    "on_battery",
    "low_battery",
    "overload",
    "replace_battery",
    "bypass",
    "power_state_unknown",
}


class ProblemBridge:
    def __init__(self):
        self.ups_refresh_requested = threading.Event()
        self.ups_reconnect_requested = threading.Event()
        self.ups_test_quick_requested = threading.Event()
        self.ups_test_deep_requested = threading.Event()
        self.ups_test_stop_requested = threading.Event()
        self.ups_test_schedule_updates = queue.SimpleQueue()
        self.discovery = []
        self.groups = []
        self.availability = []
        self.problem_calls = []
        self.fail_event_once = False

    def publish_ups_discovery(self, payload):
        self.discovery.append(payload)
        return True

    def publish_ups_state_group(self, group, payload):
        self.groups.append((group, payload))
        return True

    def publish_ups_state(self, payload):
        raise AssertionError("adaptive runtime must not use monolithic UPS state")

    def publish_ups_availability(self, online):
        self.availability.append(online)
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


def _runtime(tmp_path, current, clock, calls=None):
    bridge = ProblemBridge()

    def reader(config):
        if calls is not None:
            calls["count"] += 1
        value = current["snapshot"]
        if isinstance(value, Exception):
            raise value
        return value

    runtime = AdaptiveUpsRuntime(
        config=_config(),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.3.0",
        state_store=StateStore(tmp_path / "ups.json"),
        now_iso=lambda: clock["iso"],
        now_monotonic=lambda: clock["mono"],
        reader=reader,
        capability_reader=_capabilities,
        shutdown_policy_reader=lambda: None,
    )
    return bridge, runtime


def _healthy():
    return parse_upsc_output("ups.status: OL\nbattery.charge: 100\n")


def _on_battery():
    return parse_upsc_output("ups.status: OB DISCHRG\nbattery.charge: 90\n")


def test_startup_publishes_current_off_states_without_fake_events(tmp_path):
    current = {"snapshot": _healthy()}
    clock = {"iso": "2026-09-15T20:00:00+05:00", "mono": 0.0}
    bridge, runtime = _runtime(tmp_path, current, clock)

    assert runtime.startup() is True

    state_calls = [call for call in bridge.problem_calls if call[0] == "state"]
    assert {call[1] for call in state_calls} == PROBLEM_IDS
    assert all(call[2] is False for call in state_calls)
    assert bridge.problem_calls[-2] == ("aggregate", 0)
    presentation = bridge.problem_calls[-1]
    assert presentation[0] == "presentation"
    assert presentation[1]["severity"] == "ok"
    assert presentation[1]["active"] == []
    assert not any(call[0] == "event" for call in bridge.problem_calls)


def test_on_battery_transition_and_recovery_publish_event_last(tmp_path):
    current = {"snapshot": _healthy()}
    clock = {"iso": "2026-09-15T20:00:00+05:00", "mono": 0.0}
    bridge, runtime = _runtime(tmp_path, current, clock)
    runtime.startup()
    bridge.problem_calls.clear()

    current["snapshot"] = _on_battery()
    clock.update(iso="2026-09-15T20:00:05+05:00", mono=5.0)
    assert runtime.tick(clock["mono"]) is True

    assert [call[0] for call in bridge.problem_calls] == [
        "state",
        "aggregate",
        "presentation",
        "event",
    ]
    assert bridge.problem_calls[0] == ("state", "on_battery", True)
    assert bridge.problem_calls[1] == ("aggregate", 1)
    assert bridge.problem_calls[2][1]["severity"] == "warning"
    started = bridge.problem_calls[3][1]
    assert started["schema_version"] == 1
    assert started["event_type"] == "problem_started"
    assert started["category"] == "ups"
    assert started["metric"] == "on_battery"
    assert started["active_problem_count"] == 1

    bridge.problem_calls.clear()
    current["snapshot"] = _healthy()
    clock.update(iso="2026-09-15T20:00:10+05:00", mono=10.0)
    assert runtime.tick(clock["mono"]) is True

    assert [call[0] for call in bridge.problem_calls] == [
        "state",
        "aggregate",
        "presentation",
        "event",
    ]
    assert bridge.problem_calls[0] == ("state", "on_battery", False)
    assert bridge.problem_calls[1] == ("aggregate", 0)
    recovered = bridge.problem_calls[3][1]
    assert recovered["event_type"] == "problem_recovered"
    assert recovered["active_problem_count"] == 0


def test_nut_failure_starts_critical_problem_without_false_recoveries(tmp_path):
    current = {"snapshot": _on_battery()}
    clock = {"iso": "2026-09-15T20:00:00+05:00", "mono": 0.0}
    bridge, runtime = _runtime(tmp_path, current, clock)
    runtime.startup()
    bridge.problem_calls.clear()

    current["snapshot"] = RuntimeError("NUT offline")
    clock.update(iso="2026-09-15T20:00:05+05:00", mono=5.0)
    runtime.tick(clock["mono"])

    state_calls = [call for call in bridge.problem_calls if call[0] == "state"]
    assert state_calls == [("state", "nut_unavailable", True)]
    assert bridge.problem_calls[1] == ("aggregate", 2)
    presentation = bridge.problem_calls[2][1]
    assert presentation["severity"] == "critical"
    assert {item["problem_id"] for item in presentation["active"]} == {
        "on_battery",
        "nut_unavailable",
    }
    event = bridge.problem_calls[3][1]
    assert event["event_type"] == "problem_started"
    assert event["metric"] == "nut_unavailable"
    assert event["severity"] == "critical"
    assert event["active_problem_count"] == 2


def test_failed_event_is_retried_before_new_observation(tmp_path):
    current = {"snapshot": _healthy()}
    clock = {"iso": "2026-09-15T20:00:00+05:00", "mono": 0.0}
    calls = {"count": 0}
    bridge, runtime = _runtime(tmp_path, current, clock, calls)
    runtime.startup()
    bridge.problem_calls.clear()

    current["snapshot"] = _on_battery()
    bridge.fail_event_once = True
    clock.update(iso="2026-09-15T20:00:05+05:00", mono=5.0)
    assert runtime.tick(clock["mono"]) is False
    assert bridge.problem_calls[-1][0] == "event"
    assert bridge.problem_calls[-1][1]["event_type"] == "problem_started"

    reads_before_retry = calls["count"]
    bridge.problem_calls.clear()
    current["snapshot"] = _healthy()
    clock.update(iso="2026-09-15T20:00:10+05:00", mono=10.0)
    assert runtime.tick(clock["mono"]) is True

    # The pending started bundle is completed before the new healthy sample is
    # observed and allowed to create the recovery transition.
    assert [call[0] for call in bridge.problem_calls[:4]] == [
        "state",
        "aggregate",
        "presentation",
        "event",
    ]
    assert bridge.problem_calls[0] == ("state", "on_battery", True)
    assert bridge.problem_calls[3][1]["event_type"] == "problem_started"
    assert [call[0] for call in bridge.problem_calls[4:]] == [
        "state",
        "aggregate",
        "presentation",
        "event",
    ]
    assert bridge.problem_calls[4] == ("state", "on_battery", False)
    assert bridge.problem_calls[7][1]["event_type"] == "problem_recovered"
    assert calls["count"] == reads_before_retry + 1


def test_reconnect_republishes_problem_snapshot_without_event_or_nut_read(tmp_path):
    current = {"snapshot": _on_battery()}
    clock = {"iso": "2026-09-15T20:00:00+05:00", "mono": 0.0}
    calls = {"count": 0}
    bridge, runtime = _runtime(tmp_path, current, clock, calls)
    runtime.startup()
    before = calls["count"]
    bridge.problem_calls.clear()

    assert runtime.republish_after_reconnect() is True

    assert calls["count"] == before
    state_calls = [call for call in bridge.problem_calls if call[0] == "state"]
    assert {call[1] for call in state_calls} == PROBLEM_IDS
    assert dict((call[1], call[2]) for call in state_calls)["on_battery"] is True
    assert bridge.problem_calls[-2] == ("aggregate", 1)
    assert bridge.problem_calls[-1][0] == "presentation"
    assert not any(call[0] == "event" for call in bridge.problem_calls)
