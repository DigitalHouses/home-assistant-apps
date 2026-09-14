import queue
import threading

from app.config import MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.state_store import StateStore
from app.ups_nut import NutReadError, parse_upsc_output
from app.ups_runtime import UpsRuntime


class Bridge:
    def __init__(self):
        self.ups_refresh_requested = threading.Event()
        self.ups_reconnect_requested = threading.Event()
        self.setting_updates = queue.SimpleQueue()
        self.discovery = []
        self.states = []
        self.availability = []

    def publish_ups_discovery(self, payload):
        self.discovery.append(payload)
        return True

    def publish_ups_state(self, payload):
        self.states.append(payload)
        return True

    def publish_ups_availability(self, online):
        self.availability.append(online)
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
        name="ups",
        host="127.0.0.1",
        port=3493,
        poll_interval_seconds=5.0,
        command_timeout_seconds=3.0,
    )


def _runtime(tmp_path, reader, now=None):
    bridge = Bridge()
    clock = now or {"iso": "2026-09-12T01:00:00+00:00", "mono": 100.0}
    runtime = UpsRuntime(
        config=_config(),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.2.0",
        state_store=StateStore(tmp_path / "ups.json"),
        now_iso=lambda: clock["iso"],
        now_monotonic=lambda: clock["mono"],
        reader=reader,
    )
    return bridge, runtime, clock


def test_startup_publishes_discovery_availability_and_state(tmp_path):
    snapshot = parse_upsc_output(
        "device.mfr: CPS\ndevice.model: UT2200E\nups.status: OL\n"
        "battery.charge: 100\nbattery.runtime: 2160\nups.load: 8\n"
    )
    bridge, runtime, _ = _runtime(tmp_path, lambda config: snapshot)

    assert runtime.startup() is True
    assert bridge.availability == [True]
    assert len(bridge.discovery) == 2
    assert len(bridge.states) == 1
    assert bridge.states[-1]["available"] is True
    assert bridge.states[-1]["status"] == "Online"
    assert bridge.states[-1]["status_raw"] == "OL"
    assert bridge.states[-1]["battery_charge_percent"] == 100.0


def test_startup_removes_legacy_estimated_power_then_publishes_clean_discovery(tmp_path):
    snapshot = parse_upsc_output("ups.status: OL\nbattery.charge: 100\n")
    bridge, runtime, _ = _runtime(tmp_path, lambda config: snapshot)

    assert runtime.startup() is True
    assert bridge.discovery[0]["components"]["estimated_real_power"] == {"platform": "sensor"}
    assert "estimated_real_power" not in bridge.discovery[1]["components"]

    persisted = runtime.state_store.load()
    assert persisted["discovery_cleanup_v1"] is True
    assert "estimated_real_power" not in persisted["discovery_components"]
    assert persisted["discovery_components"]["battery_charge"] == "sensor"


def test_disappearing_capability_is_tombstoned_then_removed(tmp_path):
    current = {"snapshot": parse_upsc_output("ups.status: OL\nbattery.charge: 100\n")}
    bridge, runtime, clock = _runtime(tmp_path, lambda config: current["snapshot"])
    assert runtime.startup() is True
    bridge.discovery.clear()

    current["snapshot"] = parse_upsc_output("ups.status: OL\n")
    clock["mono"] = 105.0
    runtime.tick(clock["mono"])

    assert len(bridge.discovery) == 2
    assert bridge.discovery[0]["components"]["battery_charge"] == {"platform": "sensor"}
    assert "battery_charge" not in bridge.discovery[1]["components"]


def test_unchanged_poll_suppressed_but_ol_to_ob_publishes(tmp_path):
    current = {"snapshot": parse_upsc_output("ups.status: OL\nbattery.runtime: 2160\n")}
    bridge, runtime, clock = _runtime(tmp_path, lambda config: current["snapshot"])
    assert runtime.startup() is True
    bridge.states.clear()

    clock["mono"] = 105.0
    runtime.tick(clock["mono"])
    assert bridge.states == []

    current["snapshot"] = parse_upsc_output("ups.status: OB DISCHRG\nbattery.runtime: 2130\n")
    clock["mono"] = 110.0
    runtime.tick(clock["mono"])
    assert len(bridge.states) == 1
    assert bridge.states[-1]["status"] == "On battery"
    assert bridge.states[-1]["on_battery"] is True


def test_runtime_drift_threshold_is_five_minutes_while_online(tmp_path):
    current = {"snapshot": parse_upsc_output("ups.status: OL\nbattery.runtime: 2160\n")}
    bridge, runtime, clock = _runtime(tmp_path, lambda config: current["snapshot"])
    runtime.startup()
    bridge.states.clear()

    current["snapshot"] = parse_upsc_output("ups.status: OL\nbattery.runtime: 2100\n")
    clock["mono"] = 105.0
    runtime.tick(clock["mono"])
    assert bridge.states == []

    current["snapshot"] = parse_upsc_output("ups.status: OL\nbattery.runtime: 1860\n")
    clock["mono"] = 110.0
    runtime.tick(clock["mono"])
    assert len(bridge.states) == 1


def test_reader_failure_publishes_unavailable_without_losing_capabilities(tmp_path):
    good = parse_upsc_output("device.model: UT2200E\nups.status: OL\nbattery.charge: 100\n")
    calls = {"fail": False}

    def reader(config):
        if calls["fail"]:
            raise NutReadError("NUT недоступен")
        return good

    bridge, runtime, clock = _runtime(tmp_path, reader)
    runtime.startup()
    first_components = set(bridge.discovery[-1]["components"])
    bridge.states.clear()
    calls["fail"] = True
    clock["mono"] = 105.0

    runtime.tick(clock["mono"])

    assert bridge.states[-1]["available"] is False
    assert "NUT недоступен" in bridge.states[-1]["error"]
    assert "battery_charge" in first_components
    assert "battery_charge" in runtime.last_discovery_payload["components"]


def test_manual_refresh_updates_timestamp_only_after_success(tmp_path):
    snapshot = parse_upsc_output("ups.status: OL\n")
    should_fail = {"value": False}

    def reader(config):
        if should_fail["value"]:
            raise NutReadError("fail")
        return snapshot

    bridge, runtime, clock = _runtime(tmp_path, reader)
    runtime.startup()
    clock["iso"] = "2026-09-12T01:05:00+00:00"
    assert runtime.manual_refresh() is True
    assert bridge.states[-1]["last_refresh"] == "2026-09-12T01:05:00+00:00"

    should_fail["value"] = True
    clock["iso"] = "2026-09-12T01:06:00+00:00"
    assert runtime.manual_refresh() is False
    assert bridge.states[-1]["last_refresh"] == "2026-09-12T01:05:00+00:00"


def test_reconnect_forces_discovery_and_last_known_state(tmp_path):
    snapshot = parse_upsc_output("ups.status: OL\n")
    bridge, runtime, _ = _runtime(tmp_path, lambda config: snapshot)
    runtime.startup()
    bridge.discovery.clear()
    bridge.states.clear()

    assert runtime.republish_after_reconnect() is True
    assert len(bridge.discovery) == 1
    assert len(bridge.states) == 1
    assert bridge.states[-1]["available"] is True


def test_process_events_handles_ups_refresh_and_reconnect(tmp_path):
    snapshot = parse_upsc_output("ups.status: OL\n")
    bridge, runtime, _ = _runtime(tmp_path, lambda config: snapshot)
    runtime.startup()
    bridge.discovery.clear()
    bridge.states.clear()

    bridge.ups_refresh_requested.set()
    assert runtime.process_events() is True
    assert not bridge.ups_refresh_requested.is_set()
    assert len(bridge.states) == 1

    bridge.states.clear()
    bridge.ups_reconnect_requested.set()
    assert runtime.process_events() is True
    assert not bridge.ups_reconnect_requested.is_set()
    assert len(bridge.states) == 1
