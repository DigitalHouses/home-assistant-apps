import threading

from app.config import MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.shutdown_integration import ShutdownAwareUpsRuntime
from app.state_store import StateStore
from app.ups_nut import parse_upsc_output
from app.ups_policy import UpsPolicyDraft, policy_hash
from app.ups_shutdown_budget import ShutdownBudgetInputs, calculate_shutdown_budget


class Bridge:
    def __init__(self):
        self.ups_refresh_requested = threading.Event()
        self.ups_reconnect_requested = threading.Event()
        self.ups_test_quick_requested = threading.Event()
        self.ups_test_deep_requested = threading.Event()
        self.ups_test_stop_requested = threading.Event()
        self.discovery = []
        self.states = []
        self.events = []
        self.availability = []
        self.order = []

    def publish_ups_discovery(self, payload):
        self.discovery.append(payload)
        return True

    def publish_ups_state(self, payload):
        self.states.append(payload)
        self.order.append("state")
        return True

    def publish_ups_diagnostic_event(self, payload):
        self.events.append(payload)
        self.order.append("event")
        return True

    def publish_ups_availability(self, online):
        self.availability.append(online)
        return True


class HistoryTracker:
    def observe_ups(self, snapshot):
        return None

    def payload(self):
        return {"previous_shutdown": None, "history": [], "history_count": 0}


class VerifyMismatchStore(StateStore):
    def __init__(self, path):
        super().__init__(path)
        self.break_next_policy_verify = False

    def load(self):
        value = super().load()
        if self.break_next_policy_verify:
            self.break_next_policy_verify = False
            broken = dict(value)
            broken["policy_active"] = {
                "shutdown_battery_charge_threshold_percent": 30,
                "runtime_reserve_seconds": 900,
            }
            return broken
        return value


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


def _budget():
    return calculate_shutdown_budget(
        ShutdownBudgetInputs(280, None, 120, True, 5, None, 90)
    )


def _runtime(tmp_path, *, store_class=StateStore):
    store = store_class(tmp_path / "ups.json")
    active = UpsPolicyDraft(20, 180)
    store.save(
        {
            "policy_active": active.as_dict(),
            "policy_draft": active.as_dict(),
            "policy_status": "Active",
            "policy_revision": 4,
            "policy_hash": policy_hash(active),
            "policy_last_applied": "2026-09-15T20:00:00+05:00",
        }
    )
    bridge = Bridge()
    snapshot = parse_upsc_output(
        "ups.status: OL\nbattery.charge: 100\nbattery.runtime: 9999\n"
    )
    runtime = ShutdownAwareUpsRuntime(
        config=_config(),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.2.0",
        state_store=store,
        now_iso=lambda: "2026-09-16T01:00:00+05:00",
        now_monotonic=lambda: 100.0,
        reader=lambda config: snapshot,
        capability_reader=lambda config: (_ for _ in ()).throw(RuntimeError("skip")),
        shutdown_policy_reader=lambda: (_ for _ in ()).throw(RuntimeError("skip")),
        shutdown_history_tracker=HistoryTracker(),
        shutdown_budget_reader=_budget,
    )
    return runtime, bridge, store


def test_successful_apply_persists_verifies_then_emits_old_to_new_event_last(tmp_path):
    runtime, bridge, store = _runtime(tmp_path)
    old = runtime.policy_active
    new = UpsPolicyDraft(25, 240)
    runtime.policy_draft = new
    runtime.policy_status = "Pending changes"

    runtime._apply_policy()

    assert runtime.policy_active == new
    assert runtime.policy_draft == new
    assert runtime.policy_status == "Active"
    assert runtime.policy_revision == 5
    assert runtime.policy_hash == policy_hash(new)
    assert bridge.events == []
    persisted = store.load()
    assert persisted["policy_active"] == new.as_dict()
    assert persisted["policy_revision"] == 5

    runtime._collect(force=True)

    assert bridge.order[-1] == "event"
    assert len(bridge.events) == 1
    event = bridge.events[0]
    assert event["schema_version"] == 1
    assert event["event_type"] == "config_changed"
    assert event["category"] == "policy"
    assert event["object_id"] == "ups_trigger_policy"
    assert event["old_values"] == old.as_dict()
    assert event["new_values"] == new.as_dict()
    assert event["active_problem_count"] == 0


def test_noop_apply_does_not_increment_revision_or_emit_event(tmp_path):
    runtime, bridge, store = _runtime(tmp_path)
    original_revision = runtime.policy_revision
    original_last_applied = runtime.policy_last_applied

    runtime._apply_policy()
    runtime._collect(force=True)

    assert runtime.policy_revision == original_revision
    assert runtime.policy_last_applied == original_last_applied
    assert runtime.policy_status == "Active"
    assert runtime.policy_apply_result == "No changes"
    assert bridge.events == []
    assert store.load()["policy_revision"] == original_revision


def test_verify_mismatch_rolls_back_previous_active_policy_and_emits_no_event(tmp_path):
    runtime, bridge, store = _runtime(tmp_path, store_class=VerifyMismatchStore)
    old = runtime.policy_active
    runtime.policy_draft = UpsPolicyDraft(25, 240)
    runtime.policy_status = "Pending changes"
    store.break_next_policy_verify = True

    runtime._apply_policy()

    assert runtime.policy_active == old
    assert runtime.policy_draft == old
    assert runtime.policy_revision == 4
    assert runtime.policy_hash == policy_hash(old)
    assert runtime.policy_status == "Apply failed"
    assert bridge.events == []
    persisted = store.load()
    assert persisted["policy_active"] == old.as_dict()
    assert persisted["policy_revision"] == 4
