import queue
import threading

from app.app import CollectorSample
from app.publish_policy import MetricValue, PublishPolicy
from app.runtime_dynamic import DynamicDiscoveryRuntime
from app.runtime_settings import RuntimeSettings
from app.scheduler import Scheduler


class Store:
    def load(self):
        return {}

    def save(self, data):
        self.data = data


class Bridge:
    def __init__(self):
        self.refresh_requested = threading.Event()
        self.reconnect_requested = threading.Event()
        self.setting_updates = queue.SimpleQueue()
        self.discovery = []
        self.states = []
        self.setting_states = []
        self.discovery_payload = None

    def set_discovery_payload(self, payload):
        self.discovery_payload = payload

    def publish_discovery(self):
        self.discovery.append(self.discovery_payload)
        return True

    def publish_state(self, payload):
        self.states.append(payload)
        return True

    def publish_setting_value(self, key, value):
        self.setting_states.append((key, value))
        return True


class GroupBridge(Bridge):
    def __init__(self):
        super().__init__()
        self.group_states = []
        self.legacy_state_cleanup = 0

    def publish_state_group(self, group, payload):
        self.group_states.append((group, payload))
        return True

    def clear_legacy_state(self):
        self.legacy_state_cleanup += 1
        return True


def test_startup_builds_discovery_from_collected_inventory():
    bridge = Bridge()
    settings = RuntimeSettings()
    runtime = DynamicDiscoveryRuntime(
        collectors={
            "storage": lambda: CollectorSample(
                data={"local": {"usage_percent": 10}},
                metrics={"local": MetricValue(10, "storage_percent")},
            )
        },
        bridge=bridge,
        settings=settings,
        publish_policy=PublishPolicy(settings),
        state_store=Store(),
        scheduler=Scheduler(),
        now_iso=lambda: "2026-09-10T20:00:00+00:00",
        discovery_builder=lambda inv: {"storage": sorted(inv.get("storage", {}))},
    )

    assert runtime.startup() is True
    assert bridge.discovery == [{"storage": ["local"]}]
    assert len(bridge.states) == 1


def test_group_capable_dynamic_startup_tombstones_legacy_monolithic_state():
    bridge = GroupBridge()
    settings = RuntimeSettings()
    runtime = DynamicDiscoveryRuntime(
        collectors={},
        bridge=bridge,
        settings=settings,
        publish_policy=PublishPolicy(settings),
        state_store=Store(),
        scheduler=Scheduler(),
        now_iso=lambda: "2026-09-15T00:15:00+05:00",
        now_monotonic=lambda: 0.0,
        discovery_builder=lambda inv: {"components": {}},
    )

    assert runtime.startup() is True
    assert bridge.legacy_state_cleanup == 1
    assert bridge.states == []


def test_startup_tombstones_retired_publish_delta_discovery_components_once():
    bridge = Bridge()
    settings = RuntimeSettings()
    runtime = DynamicDiscoveryRuntime(
        collectors={},
        bridge=bridge,
        settings=settings,
        publish_policy=PublishPolicy(settings),
        state_store=Store(),
        scheduler=Scheduler(),
        now_iso=lambda: "2026-09-14T20:00:00+05:00",
        discovery_builder=lambda inv: {
            "device": {"name": "DH PVE"},
            "components": {
                "setting_fast_poll_interval_seconds": {"platform": "number"},
            },
        },
    )

    assert runtime.sync_discovery(force=True) is True
    assert len(bridge.discovery) == 2

    cleanup = bridge.discovery[0]["components"]
    for key in (
        "setting_cpu_publish_delta",
        "setting_memory_publish_delta",
        "setting_temperature_publish_delta",
        "setting_storage_publish_delta",
        "setting_fan_publish_delta_rpm",
        "setting_gpu_publish_delta",
    ):
        assert cleanup[key] == {"platform": "number"}

    assert bridge.discovery[1]["components"] == {
        "setting_fast_poll_interval_seconds": {"platform": "number"}
    }

    bridge.discovery.clear()
    assert runtime.sync_discovery(force=True) is True
    assert len(bridge.discovery) == 1
    assert not any(
        "publish_delta" in key for key in bridge.discovery[0]["components"]
    )


def test_same_discovery_shape_is_not_republished_on_metric_change():
    bridge = Bridge()
    settings = RuntimeSettings()
    value = {"n": 10}
    runtime = DynamicDiscoveryRuntime(
        collectors={
            "storage": lambda: CollectorSample(
                data={"local": {"usage_percent": value["n"]}},
                metrics={"local": MetricValue(value["n"], "storage_percent")},
            )
        },
        bridge=bridge,
        settings=settings,
        publish_policy=PublishPolicy(settings),
        state_store=Store(),
        scheduler=Scheduler(),
        now_iso=lambda: "2026-09-10T20:00:00+00:00",
        discovery_builder=lambda inv: {"storage": sorted(inv.get("storage", {}))},
    )

    runtime.startup()
    value["n"] = 20
    runtime.run_collection()

    assert bridge.discovery == [{"storage": ["local"]}]


def test_group_capable_dynamic_reconnect_republishes_group_cache_not_monolithic_state():
    calls = {"cpu": 0}

    def cpu():
        calls["cpu"] += 1
        return CollectorSample(
            data={
                "usage_percent": 20.0,
                "temperature_c": 55.0,
                "frequency": {"average_mhz": 1800.0},
                "throttling_active": False,
            },
            metrics={
                "usage_percent": MetricValue(20.0, "cpu_percent"),
                "temperature_c": MetricValue(55.0, "temperature_c"),
                "frequency_mhz": MetricValue(1800.0, "frequency_mhz"),
                "throttling_active": MetricValue(False, "discrete"),
            },
        )

    bridge = GroupBridge()
    settings = RuntimeSettings()
    runtime = DynamicDiscoveryRuntime(
        collectors={"cpu": cpu},
        bridge=bridge,
        settings=settings,
        publish_policy=PublishPolicy(settings),
        state_store=Store(),
        scheduler=Scheduler(),
        now_iso=lambda: "2026-09-14T20:00:00+05:00",
        now_monotonic=lambda: 0.0,
        discovery_builder=lambda inv: {"has_cpu": "cpu" in inv},
    )

    assert runtime.startup() is True
    cached_groups = [group for group, _ in bridge.group_states]
    before_calls = calls["cpu"]
    bridge.group_states.clear()
    bridge.states.clear()

    assert runtime.republish_after_reconnect() is True

    assert calls["cpu"] == before_calls
    assert bridge.states == []
    assert [group for group, _ in bridge.group_states] == cached_groups
    assert bridge.discovery[-1] == {"has_cpu": True}
