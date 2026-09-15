import queue
import threading
from dataclasses import dataclass

from app.app import CollectorSample, DhPveRuntime
from app.publish_policy import MetricValue, PublishPolicy
from app.runtime_settings import RuntimeSettings
from app.scheduler import Scheduler


class FakeStore:
    def __init__(self):
        self.data = {}

    def load(self):
        return dict(self.data)

    def save(self, data):
        self.data = dict(data)


class FakeBridge:
    def __init__(self):
        self.states = []
        self.discovery_count = 0
        self.setting_states = []
        self.publish_ok = True
        self.refresh_requested = threading.Event()
        self.reconnect_requested = threading.Event()
        self.setting_updates = queue.SimpleQueue()

    def publish_state(self, payload):
        self.states.append(payload)
        return self.publish_ok

    def publish_discovery(self):
        self.discovery_count += 1
        return True

    def publish_setting_value(self, key, value):
        self.setting_states.append((key, value))
        return True


@dataclass
class Update:
    key: str
    value: float


def sample(value, policy="cpu_percent"):
    return CollectorSample(data={"value": value}, metrics={"value": MetricValue(value, policy)})


def make_runtime(
    collectors,
    *,
    now_values=None,
    setting_tasks=None,
    static_collectors=(),
    slow_tasks=(),
    version_probe=None,
):
    bridge = FakeBridge()
    settings = RuntimeSettings()
    policy = PublishPolicy(settings)
    store = FakeStore()
    scheduler = Scheduler()
    clock_values = iter(now_values or ["2026-09-10T21:40:00+05:00"] * 20)
    extra = {}
    if static_collectors or slow_tasks or version_probe is not None:
        extra = {
            "static_collectors": static_collectors,
            "slow_tasks": slow_tasks,
            "version_probe": version_probe,
        }
    runtime = DhPveRuntime(
        collectors=collectors,
        bridge=bridge,
        settings=settings,
        publish_policy=policy,
        state_store=store,
        scheduler=scheduler,
        now_iso=lambda: next(clock_values),
        now_monotonic=lambda: 100.0,
        setting_tasks=setting_tasks,
        **extra,
    )
    return runtime, bridge, policy, store, scheduler


def test_startup_publishes_discovery_settings_and_initial_state():
    runtime, bridge, policy, _, _ = make_runtime({"cpu": lambda: sample(10.0)})
    assert runtime.startup() is True
    assert bridge.discovery_count == 1
    assert len(bridge.setting_states) == len(runtime.settings.as_dict())
    assert bridge.states[-1]["subsystems"]["cpu"]["available"] is True
    assert policy.last_published() is not None


def test_unchanged_below_threshold_state_is_suppressed_without_heartbeat():
    values = iter([10.0, 12.0])
    runtime, bridge, _, _, _ = make_runtime({"cpu": lambda: sample(next(values))})
    assert runtime.run_collection(force=True) is True
    assert runtime.run_collection() is False
    assert len(bridge.states) == 1


def test_failed_publish_does_not_advance_publish_baseline():
    runtime, bridge, policy, _, _ = make_runtime({"cpu": lambda: sample(10.0)})
    bridge.publish_ok = False
    assert runtime.run_collection() is False
    assert policy.last_published() is None
    bridge.publish_ok = True
    assert runtime.run_collection() is True
    assert len(bridge.states) == 2
    assert policy.last_published() is not None


def test_one_collector_failure_only_marks_that_subsystem_unavailable():
    def broken():
        raise RuntimeError("smartctl timeout")

    runtime, bridge, _, _, _ = make_runtime({"cpu": lambda: sample(20.0), "smart": broken})
    assert runtime.run_collection(force=True) is True
    state = bridge.states[-1]["subsystems"]
    assert state["cpu"]["available"] is True
    assert state["smart"]["available"] is False
    assert state["smart"]["error"] == "RuntimeError: smartctl timeout"


def test_collector_recovery_is_an_immediate_discrete_publish():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("failed")
        return sample(10.0)

    runtime, bridge, _, _, _ = make_runtime({"smart": flaky})
    assert runtime.run_collection(force=True) is True
    assert runtime.run_collection() is True
    assert bridge.states[-1]["subsystems"]["smart"]["available"] is True


def test_manual_refresh_runs_all_collectors_and_updates_timestamp_only_when_all_succeed():
    calls = {"cpu": 0, "disk": 0}

    def cpu():
        calls["cpu"] += 1
        return sample(10.0)

    def disk():
        calls["disk"] += 1
        return sample(30.0, "storage_percent")

    runtime, bridge, _, _, _ = make_runtime(
        {"cpu": cpu, "disk": disk},
        now_values=["2026-09-10T21:41:00+05:00"] * 20,
    )
    assert runtime.manual_refresh() is True
    assert calls == {"cpu": 1, "disk": 1}
    assert runtime.last_refresh == "2026-09-10T21:41:00+05:00"
    assert bridge.states[-1]["last_refresh"] == runtime.last_refresh


def test_manual_refresh_with_partial_failure_keeps_previous_last_refresh():
    def broken():
        raise RuntimeError("no sensor")

    runtime, bridge, _, _, _ = make_runtime({"cpu": lambda: sample(10.0), "fan": broken})
    runtime.last_refresh = "2026-09-09T10:00:00+05:00"
    assert runtime.manual_refresh() is True
    assert runtime.last_refresh == "2026-09-09T10:00:00+05:00"
    assert bridge.states[-1]["last_refresh"] == "2026-09-09T10:00:00+05:00"


def test_reconnect_republishes_discovery_settings_and_current_state_without_collecting():
    calls = {"cpu": 0}

    def cpu():
        calls["cpu"] += 1
        return sample(10.0)

    runtime, bridge, _, _, _ = make_runtime({"cpu": cpu})
    runtime.run_collection(force=True)
    before = calls["cpu"]
    bridge.reconnect_requested.set()
    assert runtime.process_events() is True
    assert calls["cpu"] == before
    assert bridge.discovery_count == 1
    assert len(bridge.states) == 2


def test_refresh_event_runs_manual_refresh():
    calls = {"cpu": 0}

    def cpu():
        calls["cpu"] += 1
        return sample(10.0)

    runtime, bridge, _, _, _ = make_runtime({"cpu": cpu})
    bridge.refresh_requested.set()
    assert runtime.process_events() is True
    assert calls["cpu"] == 1
    assert runtime.last_refresh is not None


def test_scheduler_runs_only_due_collectors():
    calls = {"fast": 0, "slow": 0}

    def fast():
        calls["fast"] += 1
        return sample(10.0)

    def slow():
        calls["slow"] += 1
        return sample(10.0)

    runtime, _, _, _, scheduler = make_runtime({"fast": fast, "slow": slow})
    scheduler.add("fast", interval_seconds=10, now=0)
    scheduler.add("slow", interval_seconds=60, now=0)
    runtime.tick(10)
    assert calls == {"fast": 1, "slow": 0}


def test_slow_version_change_refreshes_static_exactly_once():
    calls = {"static": 0, "slow": 0}
    fingerprints = iter(["A", "A", "B", "B"])

    def static():
        calls["static"] += 1
        return sample(calls["static"], "discrete")

    def slow():
        calls["slow"] += 1
        return sample(calls["slow"])

    runtime, _, _, _, scheduler = make_runtime(
        {"static": static, "slow": slow},
        static_collectors=("static",),
        slow_tasks=("slow",),
        version_probe=lambda: next(fingerprints),
    )
    scheduler.add("slow", interval_seconds=60, now=0)

    assert runtime.startup() is True
    assert calls == {"static": 1, "slow": 1}

    runtime.tick(60)
    assert calls == {"static": 1, "slow": 2}

    runtime.tick(120)
    assert calls == {"static": 2, "slow": 3}

    runtime.tick(180)
    assert calls == {"static": 2, "slow": 4}
