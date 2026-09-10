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
