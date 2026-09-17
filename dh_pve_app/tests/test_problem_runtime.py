import queue
import threading

from app.app import CollectorSample
from app.mqtt_bridge import SettingUpdate
from app.publish_policy import PublishPolicy
from app.runtime_problems import ProblemAwareRuntime
from app.runtime_settings import RuntimeSettings
from app.scheduler import Scheduler


class FakeStore:
    def __init__(self):
        self.data = {}

    def load(self):
        return dict(self.data)

    def save(self, data):
        self.data = dict(data)


class RecordingBridge:
    def __init__(self):
        self.calls = []
        self.refresh_requested = threading.Event()
        self.reconnect_requested = threading.Event()
        self.setting_updates = queue.SimpleQueue()
        self.fail_once = set()
        self.discovery_payload = None

    def _result(self, kind):
        if kind in self.fail_once:
            self.fail_once.remove(kind)
            return False
        return True

    def clear_legacy_state(self):
        self.calls.append(("legacy_cleanup",))
        return self._result("legacy_cleanup")

    def set_discovery_payload(self, payload):
        self.discovery_payload = payload

    def publish_discovery(self):
        self.calls.append(("discovery",))
        return self._result("discovery")

    def publish_state(self, payload):
        self.calls.append(("state", payload))
        return self._result("state")

    def publish_state_group(self, group, payload):
        self.calls.append(("state_group", group, payload))
        return self._result("state_group")

    def publish_setting_value(self, key, value):
        self.calls.append(("setting", key, value))
        return self._result("setting")

    def publish_problem_metric(self, problem_id, payload):
        self.calls.append(("problem_metric", problem_id, payload))
        return self._result("problem_metric")

    def publish_problem_state(self, problem_id, active):
        self.calls.append(("problem_state", problem_id, active))
        return self._result("problem_state")

    def publish_problem_aggregate(self, count):
        self.calls.append(("problem_aggregate", count))
        return self._result("problem_aggregate")

    def publish_problem_presentation(self, payload):
        self.calls.append(("problem_presentation", payload))
        return self._result("problem_presentation")

    def publish_diagnostic_event(self, payload):
        self.calls.append(("diagnostic_event", payload))
        return self._result("diagnostic_event")


class CpuCollector:
    def __init__(self, temperature):
        self.temperature = temperature

    def __call__(self):
        return CollectorSample(
            data={"temperature_c": self.temperature, "throttling_active": False},
            metrics={},
        )


def make_runtime(*, temperature=95.0):
    bridge = RecordingBridge()
    settings = RuntimeSettings()
    store = FakeStore()
    scheduler = Scheduler()
    scheduler.add("cpu", interval_seconds=10.0, now=0.0)
    clock = {"now": 0.0}
    cpu = CpuCollector(temperature)
    runtime = ProblemAwareRuntime(
        collectors={"cpu": cpu},
        bridge=bridge,
        settings=settings,
        publish_policy=PublishPolicy(settings),
        state_store=store,
        scheduler=scheduler,
        now_iso=lambda: "2026-09-16T00:00:00+00:00",
        now_monotonic=lambda: clock["now"],
        discovery_builder=lambda inventory: {"device": {}, "components": {}},
    )
    return runtime, bridge, store, scheduler, clock, cpu


def problem_calls(bridge):
    kinds = {
        "problem_metric",
        "setting",
        "problem_state",
        "problem_aggregate",
        "problem_presentation",
        "diagnostic_event",
    }
    return [call for call in bridge.calls if call[0] in kinds]


def test_initial_inactive_problem_state_is_retained_without_recovery_event():
    runtime, bridge, _store, _scheduler, clock, _cpu = make_runtime(temperature=80.0)

    runtime.run_collection(("cpu",), force=True)
    bridge.calls.clear()
    clock["now"] = 60.0
    runtime.run_collection(("cpu",), force=True)

    calls = problem_calls(bridge)
    assert [call[0] for call in calls] == [
        "problem_metric",
        "setting",
        "problem_state",
        "problem_aggregate",
        "problem_presentation",
    ]
    assert calls[0][1] == "cpu_temperature"
    assert calls[1] == ("setting", "cpu_temperature_threshold", 90.0)
    assert calls[2] == ("problem_state", "cpu_temperature", False)
    assert calls[3] == ("problem_aggregate", 0)
    assert calls[4][1] == {"severity": "ok", "active": []}
    assert not any(call[0] == "diagnostic_event" for call in calls)

    bridge.calls.clear()
    clock["now"] = 61.0
    runtime.run_collection(("cpu",), force=True)
    assert problem_calls(bridge) == []


def test_problem_transition_bundle_publishes_event_last_in_exact_order():
    runtime, bridge, _store, _scheduler, clock, _cpu = make_runtime(temperature=95.0)

    runtime.run_collection(("cpu",), force=True)
    bridge.calls.clear()
    clock["now"] = 60.0
    runtime.run_collection(("cpu",), force=True)

    calls = problem_calls(bridge)
    assert [call[0] for call in calls] == [
        "problem_metric",
        "setting",
        "problem_state",
        "problem_aggregate",
        "problem_presentation",
        "diagnostic_event",
    ]
    assert calls[0] == (
        "problem_metric",
        "cpu_temperature",
        {"metric": "temperature_c", "value": 95.0, "average": 95.0},
    )
    assert calls[1] == ("setting", "cpu_temperature_threshold", 90.0)
    assert calls[2] == ("problem_state", "cpu_temperature", True)
    assert calls[3] == ("problem_aggregate", 1)
    assert calls[4][1]["severity"] == "warning"
    assert "summary" not in calls[4][1]
    assert calls[4][1]["active"][0]["problem_id"] == "cpu_temperature"
    assert "summary" not in calls[4][1]["active"][0]
    event = calls[5][1]
    assert event["schema_version"] == 2
    assert event["event_type"] == "problem_started"
    assert event["observed_at"] == "2026-09-16T00:00:00+00:00"
    assert event["previous"]["active"] is False
    assert event["current"]["active"] is True
    assert event["current"]["average"] == 95.0
    assert event["active_problem_count"] == 1
    assert not ({"summary", "details", "value", "average", "threshold"} & event.keys())


def test_failed_retained_problem_publish_blocks_event_and_retries_before_new_observation():
    runtime, bridge, _store, _scheduler, clock, _cpu = make_runtime(temperature=95.0)

    runtime.run_collection(("cpu",), force=True)
    bridge.calls.clear()
    bridge.fail_once.add("problem_state")
    clock["now"] = 60.0
    runtime.run_collection(("cpu",), force=True)

    first = problem_calls(bridge)
    assert [call[0] for call in first] == [
        "problem_metric",
        "setting",
        "problem_state",
    ]
    assert not any(call[0] == "diagnostic_event" for call in first)

    bridge.calls.clear()
    clock["now"] = 61.0
    runtime.run_collection(("cpu",), force=True)
    retried = problem_calls(bridge)
    assert [call[0] for call in retried] == [
        "problem_metric",
        "setting",
        "problem_state",
        "problem_aggregate",
        "problem_presentation",
        "diagnostic_event",
    ]
    assert retried[-1][1]["event_type"] == "problem_started"
    assert retried[-1][1]["schema_version"] == 2


def test_threshold_update_reevaluates_persists_and_never_changes_scheduler_interval():
    runtime, bridge, store, scheduler, clock, _cpu = make_runtime(temperature=85.0)

    runtime.run_collection(("cpu",), force=True)
    clock["now"] = 60.0
    runtime.run_collection(("cpu",), force=True)
    bridge.calls.clear()

    before_interval = scheduler.interval("cpu")
    value = runtime.settings.apply("cpu_temperature_threshold", "80")
    bridge.setting_updates.put(
        SettingUpdate(key="cpu_temperature_threshold", value=value)
    )

    assert runtime.process_events() is True

    calls = problem_calls(bridge)
    assert [call[0] for call in calls] == [
        "problem_metric",
        "setting",
        "problem_state",
        "problem_aggregate",
        "problem_presentation",
        "diagnostic_event",
    ]
    assert calls[1] == ("setting", "cpu_temperature_threshold", 80.0)
    assert calls[-1][1]["event_type"] == "problem_started"
    assert calls[-1][1]["schema_version"] == 2
    assert calls[-1][1]["current"]["average"] == 85.0
    assert scheduler.interval("cpu") == before_interval == 10.0
    assert store.data["runtime_settings"]["cpu_temperature_threshold"] == 80.0
