import queue
import threading

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


class GroupBridge:
    def __init__(self):
        self.group_states = []
        self.legacy_states = []
        self.discovery_count = 0
        self.setting_states = []
        self.legacy_state_cleanup = 0
        self.refresh_requested = threading.Event()
        self.reconnect_requested = threading.Event()
        self.setting_updates = queue.SimpleQueue()
        self.fail_group = None

    def publish_state_group(self, group, payload):
        self.group_states.append((group, payload))
        return group != self.fail_group

    def publish_state(self, payload):
        self.legacy_states.append(payload)
        return True

    def publish_discovery(self):
        self.discovery_count += 1
        return True

    def publish_setting_value(self, key, value):
        self.setting_states.append((key, value))
        return True

    def clear_legacy_state(self):
        self.legacy_state_cleanup += 1
        return True


def cpu_sample(usage=20.0, temperature=55.0, throttling=False):
    data = {
        "usage_percent": usage,
        "temperature_c": temperature,
        "frequency": {"average_mhz": 1800.0},
        "throttling_active": throttling,
    }
    return CollectorSample(
        data=data,
        metrics={
            "usage_percent": MetricValue(usage, "cpu_percent"),
            "temperature_c": MetricValue(temperature, "temperature_c"),
            "frequency_mhz": MetricValue(1800.0, "frequency_mhz"),
            "throttling_active": MetricValue(throttling, "discrete"),
        },
    )


def memory_sample(usage=80.0):
    data = {
        "usage_percent": usage,
        "swap_usage_percent": 0.0,
        "total_gib": 16.0,
        "used_gib": 12.8,
        "available_gib": 3.2,
        "swap_total_gib": 4.0,
        "swap_used_gib": 0.0,
    }
    return CollectorSample(
        data=data,
        metrics={
            "usage_percent": MetricValue(usage, "memory_percent"),
            "swap_usage_percent": MetricValue(0.0, "memory_percent"),
        },
    )


def make_runtime(collectors, *, mono_values=None, iso_values=None, app_version=None):
    bridge = GroupBridge()
    settings = RuntimeSettings()
    policy = PublishPolicy(settings)
    mono = iter(mono_values or [0.0] * 20)
    iso = iter(iso_values or ["2026-09-14T20:00:00+05:00"] * 20)
    kwargs = {}
    if app_version is not None:
        kwargs["app_version"] = app_version
    runtime = DhPveRuntime(
        collectors=collectors,
        bridge=bridge,
        settings=settings,
        publish_policy=policy,
        state_store=FakeStore(),
        scheduler=Scheduler(),
        now_iso=lambda: next(iso),
        now_monotonic=lambda: next(mono),
        **kwargs,
    )
    return runtime, bridge


def test_group_capable_runtime_does_not_publish_monolithic_state():
    runtime, bridge = make_runtime({"cpu": lambda: cpu_sample()})

    assert runtime.run_collection(force=True) is True

    assert bridge.legacy_states == []
    assert {group for group, _ in bridge.group_states} >= {
        "cpu",
        "collector/cpu",
        "diagnostics",
    }


def test_group_capable_runtime_publishes_app_version_in_diagnostics():
    runtime, bridge = make_runtime(
        {"cpu": lambda: cpu_sample()},
        app_version="0.5.1",
    )

    assert runtime.run_collection(force=True) is True

    diagnostics = dict(bridge.group_states)["diagnostics"]
    assert diagnostics["app_version"] == "0.5.1"


def test_group_capable_startup_tombstones_legacy_monolithic_state():
    runtime, bridge = make_runtime({"cpu": lambda: cpu_sample()})

    assert runtime.startup() is True

    assert bridge.legacy_state_cleanup == 1
    assert bridge.legacy_states == []


def test_cpu_profile_transition_only_publishes_cpu_resource_plus_diagnostics():
    usages = iter([70.0, 90.0])
    runtime, bridge = make_runtime(
        {"cpu": lambda: cpu_sample(usage=next(usages))},
        mono_values=[0.0, 60.1],
        iso_values=[
            "2026-09-14T20:00:00+05:00",
            "2026-09-14T20:01:00+05:00",
        ],
    )
    runtime.run_collection(force=True)
    bridge.group_states.clear()

    assert runtime.run_collection(names=("cpu",)) is True

    assert [group for group, _ in bridge.group_states] == ["cpu", "diagnostics"]
    diagnostics = bridge.group_states[-1][1]
    assert diagnostics["app_profile"]["state"] == "detail"
    assert diagnostics["last_publication"]["group"] == "cpu"
    assert diagnostics["last_publication"]["reason"] == "profile_transition"


def test_detail_transition_does_not_mutate_scheduler_collection_cadence():
    usages = iter([70.0, 90.0])
    runtime, _bridge = make_runtime(
        {"cpu": lambda: cpu_sample(usage=next(usages))},
        mono_values=[0.0, 60.1],
    )
    runtime.scheduler.add("cpu", interval_seconds=10.0, now=0.0)
    runtime.scheduler.add("gpu", interval_seconds=60.0, now=0.0)
    runtime.scheduler.add("smart", interval_seconds=3600.0, now=0.0)
    before = {name: runtime.scheduler.interval(name) for name in runtime.scheduler.names()}

    runtime.run_collection(force=True)
    runtime.run_collection(names=("cpu",))

    after = {name: runtime.scheduler.interval(name) for name in runtime.scheduler.names()}
    assert after == before


def test_manual_refresh_publishes_all_current_resource_groups_and_updates_refresh_time():
    runtime, bridge = make_runtime(
        {"cpu": lambda: cpu_sample(), "memory": lambda: memory_sample()},
        mono_values=[0.0, 10.0],
        iso_values=[
            "2026-09-14T20:00:00+05:00",
            "2026-09-14T20:00:10+05:00",
        ],
    )
    runtime.run_collection(force=True)
    bridge.group_states.clear()

    assert runtime.manual_refresh() is True

    groups = [group for group, _ in bridge.group_states]
    assert groups[:-1] == ["collector/cpu", "cpu", "collector/memory", "memory"]
    assert groups[-1] == "diagnostics"
    assert runtime.last_refresh == "2026-09-14T20:00:10+05:00"
    assert bridge.group_states[-1][1]["last_refresh"] == runtime.last_refresh
    assert bridge.group_states[-1][1]["last_publication"]["reason"] == "manual_refresh"


def test_reconnect_republishes_cached_groups_without_collecting_or_touching_buckets():
    calls = {"cpu": 0}

    def cpu():
        calls["cpu"] += 1
        return cpu_sample()

    runtime, bridge = make_runtime({"cpu": cpu}, mono_values=[0.0])
    assert runtime.run_collection(force=True) is True
    cached_groups = [group for group, _ in bridge.group_states]
    before_calls = calls["cpu"]
    bridge.group_states.clear()

    bridge.reconnect_requested.set()
    assert runtime.process_events() is True

    assert calls["cpu"] == before_calls
    assert [group for group, _ in bridge.group_states] == cached_groups
    assert bridge.discovery_count == 1


def test_failed_group_publish_prevents_manual_refresh_timestamp_advance():
    runtime, bridge = make_runtime(
        {"cpu": lambda: cpu_sample(), "memory": lambda: memory_sample()},
        mono_values=[0.0],
        iso_values=["2026-09-14T20:00:00+05:00"],
    )
    bridge.fail_group = "memory"

    assert runtime.manual_refresh() is False
    assert runtime.last_refresh is None
    assert all(group != "diagnostics" for group, _ in bridge.group_states)


def test_successful_pending_group_retry_updates_last_publication_diagnostics():
    runtime, bridge = make_runtime(
        {"cpu": lambda: cpu_sample()},
        mono_values=[0.0, 10.0],
        iso_values=[
            "2026-09-14T20:00:00+05:00",
            "2026-09-14T20:00:10+05:00",
        ],
    )
    bridge.fail_group = "cpu"

    assert runtime.run_collection(force=True) is False
    assert "cpu" in runtime._pending_groups
    bridge.group_states.clear()

    bridge.fail_group = None
    assert runtime.run_collection(names=("cpu",)) is True

    assert [group for group, _ in bridge.group_states] == ["cpu", "diagnostics"]
    diagnostics = bridge.group_states[-1][1]
    assert diagnostics["last_publication"]["group"] == "cpu"
    assert diagnostics["last_publication"]["reason"] == "retry"
    assert diagnostics["last_publication"]["group_count"] == 1
