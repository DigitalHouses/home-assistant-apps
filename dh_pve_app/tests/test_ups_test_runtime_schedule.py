import queue
import threading
from datetime import datetime, timedelta, timezone

from app.config import MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.mqtt_bridge import TestScheduleUpdate
from app.state_store import StateStore
from app.ups_control import UpsCapabilities
from app.ups_nut import parse_upsc_output
from app.ups_runtime import UpsRuntime


TZ = timezone(timedelta(hours=5))


class Bridge:
    def __init__(self):
        self.ups_refresh_requested = threading.Event()
        self.ups_reconnect_requested = threading.Event()
        self.ups_test_quick_requested = threading.Event()
        self.ups_test_deep_requested = threading.Event()
        self.ups_test_stop_requested = threading.Event()
        self.ups_policy_apply_requested = threading.Event()
        self.ups_policy_updates = queue.SimpleQueue()
        self.ups_test_schedule_updates = queue.SimpleQueue()
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


def _capabilities():
    return UpsCapabilities(
        commands=(
            "test.battery.start.quick",
            "test.battery.start.deep",
            "test.battery.stop",
        ),
        battery_tests=("quick", "deep", "stop"),
        beeper_control=False,
        load_control=False,
        shutdown_control=False,
        supported_features=("Battery tests",),
        controls_enabled=True,
    )


def _safe_snapshot():
    return parse_upsc_output(
        "ups.status: OL\n"
        "battery.charge: 100\n"
        "battery.runtime: 7200\n"
        "ups.load: 6\n"
    )


def _stored_schedule(
    *,
    quick_anchor="2026-08-14T12:00:00+05:00",
    deep_anchor="2026-09-01T13:00:00+05:00",
    quick_time="12:00",
    deep_time="13:00",
):
    return {
        "test_schedule": {
            "quick": {
                "interval_days": 30,
                "preferred_time": quick_time,
                "anchor": quick_anchor,
                "last_window_date": None,
            },
            "deep": {
                "interval_days": 180,
                "preferred_time": deep_time,
                "anchor": deep_anchor,
                "last_window_date": None,
            },
            "last_decision": None,
        },
        "test_history": [],
    }


def _runtime(tmp_path, *, clock, snapshot_holder=None, persisted=None, command_calls=None):
    bridge = Bridge()
    store = StateStore(tmp_path / "ups.json")
    if persisted is not None:
        store.save(persisted)
    holder = snapshot_holder or {"value": _safe_snapshot()}
    calls = command_calls if command_calls is not None else []

    runtime = UpsRuntime(
        config=_config(),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.2.0",
        state_store=store,
        now_iso=lambda: clock["local"].astimezone(timezone.utc).isoformat(),
        now_local=lambda: clock["local"],
        now_monotonic=lambda: clock["mono"],
        reader=lambda config: holder["value"],
        capability_reader=lambda config: _capabilities(),
        command_executor=lambda config, action: calls.append(action),
        shutdown_policy_reader=lambda: (_ for _ in ()).throw(RuntimeError("not needed")),
    )
    return bridge, runtime, store, holder, calls


def test_default_schedules_are_local_persistent_and_not_immediate(tmp_path):
    clock = {"local": datetime(2026, 9, 13, 10, 0, tzinfo=TZ), "mono": 100.0}
    bridge, runtime, store, _, calls = _runtime(tmp_path, clock=clock)

    assert runtime.startup() is True
    schedule = bridge.states[-1]["test_schedule"]
    assert schedule["quick"]["interval_days"] == 30
    assert schedule["quick"]["preferred_time"] == "12:00"
    assert schedule["quick"]["next_due"] == "2026-10-13T12:00:00+05:00"
    assert schedule["deep"]["interval_days"] == 180
    assert schedule["deep"]["preferred_time"] == "13:00"
    assert schedule["deep"]["next_due"] == "2027-03-12T13:00:00+05:00"
    assert schedule["current_state"] == "Idle"
    assert calls == []
    assert store.load()["test_schedule"]["quick"]["anchor"] == "2026-09-13T10:00:00+05:00"


def test_schedule_update_resets_anchor_and_persists(tmp_path):
    clock = {"local": datetime(2026, 9, 13, 11, 0, tzinfo=TZ), "mono": 100.0}
    bridge, runtime, store, _, _ = _runtime(tmp_path, clock=clock)
    runtime.startup()
    bridge.ups_test_schedule_updates.put(
        TestScheduleUpdate(test_type="quick", field="interval_days", value=7)
    )

    assert runtime.process_events() is True
    persisted = store.load()["test_schedule"]["quick"]
    assert persisted["interval_days"] == 7
    assert persisted["anchor"] == "2026-09-13T11:00:00+05:00"
    assert bridge.states[-1]["test_schedule"]["quick"]["next_due"] == "2026-09-20T12:00:00+05:00"


def test_due_safe_quick_test_runs_once_and_is_recorded(tmp_path):
    clock = {"local": datetime(2026, 9, 13, 12, 5, tzinfo=TZ), "mono": 100.0}
    bridge, runtime, store, _, calls = _runtime(
        tmp_path,
        clock=clock,
        persisted=_stored_schedule(),
    )
    runtime.startup()
    clock["mono"] = 105.0

    assert runtime.tick(clock["mono"]) is True
    assert calls == ["quick"]
    persisted = store.load()
    assert persisted["test_schedule"]["quick"]["anchor"] == "2026-09-13T12:05:00+05:00"
    assert persisted["test_history"][-1]["type"] == "Quick"
    assert persisted["test_history"][-1]["source"] == "Scheduled"

    clock["mono"] = 110.0
    runtime.tick(clock["mono"])
    assert calls == ["quick"]


def test_overdue_test_waits_for_later_eligible_window_when_unsafe(tmp_path):
    clock = {"local": datetime(2026, 9, 13, 12, 5, tzinfo=TZ), "mono": 100.0}
    holder = {"value": parse_upsc_output("ups.status: OB DISCHRG\nbattery.charge: 90\n")}
    _, runtime, store, holder, calls = _runtime(
        tmp_path,
        clock=clock,
        snapshot_holder=holder,
        persisted=_stored_schedule(),
    )
    runtime.startup()
    clock["mono"] = 105.0
    runtime.tick(clock["mono"])
    assert calls == []
    assert store.load()["test_schedule"]["quick"]["anchor"] == "2026-08-14T12:00:00+05:00"

    holder["value"] = _safe_snapshot()
    clock["local"] = datetime(2026, 9, 13, 12, 30, tzinfo=TZ)
    clock["mono"] = 110.0
    runtime.tick(clock["mono"])
    assert calls == []

    clock["local"] = datetime(2026, 9, 14, 12, 5, tzinfo=TZ)
    clock["mono"] = 115.0
    runtime.tick(clock["mono"])
    assert calls == ["quick"]


def test_overdue_test_does_not_start_at_night(tmp_path):
    clock = {"local": datetime(2026, 9, 13, 23, 0, tzinfo=TZ), "mono": 100.0}
    _, runtime, store, _, calls = _runtime(
        tmp_path,
        clock=clock,
        persisted=_stored_schedule(),
    )
    runtime.startup()
    clock["mono"] = 105.0
    runtime.tick(clock["mono"])

    assert calls == []
    assert store.load()["test_schedule"]["quick"]["anchor"] == "2026-08-14T12:00:00+05:00"


def test_deep_priority_defers_quick_until_next_eligible_day(tmp_path):
    clock = {"local": datetime(2026, 9, 13, 12, 5, tzinfo=TZ), "mono": 100.0}
    persisted = _stored_schedule(
        deep_anchor="2026-03-17T12:00:00+05:00",
        deep_time="12:00",
    )
    _, runtime, store, _, calls = _runtime(tmp_path, clock=clock, persisted=persisted)
    runtime.startup()
    clock["mono"] = 105.0
    runtime.tick(clock["mono"])

    assert calls == ["deep"]
    state = store.load()["test_schedule"]
    assert state["quick"]["anchor"] == "2026-08-14T12:00:00+05:00"
    assert state["last_decision"] == "Deep priority; Quick deferred"

    clock["mono"] = 110.0
    runtime.tick(clock["mono"])
    assert calls == ["deep"]

    clock["local"] = datetime(2026, 9, 14, 12, 5, tzinfo=TZ)
    clock["mono"] = 115.0
    runtime.tick(clock["mono"])
    assert calls == ["deep", "quick"]


def test_manual_test_history_is_capped_to_ten_and_survives_restart(tmp_path):
    clock = {"local": datetime(2026, 9, 13, 14, 0, tzinfo=TZ), "mono": 100.0}
    bridge, runtime, store, _, _ = _runtime(tmp_path, clock=clock)
    runtime.startup()

    for index in range(12):
        clock["local"] = datetime(2026, 9, 13, 14, index, tzinfo=TZ)
        bridge.ups_test_quick_requested.set()
        assert runtime.process_events() is True

    history = store.load()["test_history"]
    assert len(history) == 10
    assert all(item["source"] == "Manual" for item in history)
    assert all(item["type"] == "Quick" for item in history)

    _, restarted, _, _, _ = _runtime(tmp_path, clock=clock, persisted=store.load())
    assert restarted.test_history == history
