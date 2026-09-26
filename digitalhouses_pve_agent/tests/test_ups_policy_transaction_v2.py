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


class ReloadRecorder:
    def __init__(self, *, error=None):
        self.calls = 0
        self.error = error

    def __call__(self):
        self.calls += 1
        if self.error is not None:
            raise self.error


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
        topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
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


def _runtime(tmp_path, *, store_class=StateStore, reload_executor=None):
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
    reload_executor = reload_executor or ReloadRecorder()
    runtime = ShutdownAwareUpsRuntime(
        config=_config(),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.5.0",
        state_store=store,
        now_iso=lambda: "2026-09-16T01:00:00+05:00",
        now_monotonic=lambda: 100.0,
        reader=lambda config: snapshot,
        capability_reader=lambda config: (_ for _ in ()).throw(RuntimeError("skip")),
        shutdown_policy_reader=lambda: (_ for _ in ()).throw(RuntimeError("skip")),
        shutdown_history_tracker=HistoryTracker(),
        shutdown_budget_reader=_budget,
        policy_reload_executor=reload_executor,
    )
    return runtime, bridge, store, reload_executor


def test_changed_apply_persists_pending_transaction_and_requests_service_reload(tmp_path):
    runtime, bridge, store, reloads = _runtime(tmp_path)
    old = runtime.policy_active
    new = UpsPolicyDraft(25, 240)
    runtime.policy_draft = new
    runtime.policy_status = "Pending changes"

    runtime._apply_policy()

    assert reloads.calls == 1
    assert runtime.policy_active == old
    assert runtime.policy_draft == new
    assert runtime.policy_status == "Applying"
    assert runtime.policy_revision == 4
    assert bridge.events == []

    persisted = store.load()
    assert persisted["policy_active"] == old.as_dict()
    assert persisted["policy_revision"] == 4
    transaction = runtime.policy_apply_store.load()
    assert transaction["phase"] == "reload_requested"
    assert transaction["old_values"] == old.as_dict()
    assert transaction["new_values"] == new.as_dict()
    assert transaction["target_revision"] == 5
    assert transaction["target_hash"] == policy_hash(new)


def test_reload_completion_promotes_policy_verifies_then_emits_machine_v2_event_last(tmp_path):
    runtime, bridge, store, reloads = _runtime(tmp_path)
    old = runtime.policy_active
    new = UpsPolicyDraft(25, 240)
    runtime.policy_draft = new
    runtime.policy_status = "Pending changes"

    runtime._apply_policy()
    assert reloads.calls == 1
    assert runtime.complete_policy_reload() is True

    assert runtime.policy_active == new
    assert runtime.policy_draft == new
    assert runtime.policy_status == "Active"
    assert runtime.policy_revision == 5
    assert runtime.policy_hash == policy_hash(new)
    assert runtime.policy_apply_store.load() == {}

    assert bridge.order[-1] == "event"
    assert len(bridge.events) == 1
    event = bridge.events[0]
    assert event == {
        "schema_version": 2,
        "event_type": "config_changed",
        "observed_at": "2026-09-16T01:00:00+05:00",
        "old_values": old.as_dict(),
        "new_values": new.as_dict(),
        "previous_revision": 4,
        "current_revision": 5,
    }
    assert not ({"summary", "details", "title", "message", "status_ru"} & event.keys())


def test_noop_apply_does_not_reload_increment_revision_or_emit_event(tmp_path):
    runtime, bridge, store, reloads = _runtime(tmp_path)
    original_revision = runtime.policy_revision
    original_last_applied = runtime.policy_last_applied

    runtime._apply_policy()
    runtime._collect(force=True)

    assert reloads.calls == 0
    assert runtime.policy_revision == original_revision
    assert runtime.policy_last_applied == original_last_applied
    assert runtime.policy_status == "Active"
    assert runtime.policy_apply_result == "No changes"
    assert bridge.events == []
    assert store.load()["policy_revision"] == original_revision
    assert runtime.policy_apply_store.load() == {}


def test_reload_request_failure_rolls_back_pending_draft_and_keeps_active(tmp_path):
    reloads = ReloadRecorder(error=RuntimeError("reload failed"))
    runtime, bridge, store, _ = _runtime(tmp_path, reload_executor=reloads)
    old = runtime.policy_active
    runtime.policy_draft = UpsPolicyDraft(25, 240)
    runtime.policy_status = "Pending changes"

    runtime._apply_policy()

    assert reloads.calls == 1
    assert runtime.policy_active == old
    assert runtime.policy_draft == old
    assert runtime.policy_revision == 4
    assert runtime.policy_hash == policy_hash(old)
    assert runtime.policy_status == "Apply failed"
    assert bridge.events == []
    assert runtime.policy_apply_store.load() == {}
    assert store.load()["policy_active"] == old.as_dict()


def test_verify_mismatch_after_reload_rolls_back_previous_active_and_emits_no_event(tmp_path):
    runtime, bridge, store, reloads = _runtime(
        tmp_path,
        store_class=VerifyMismatchStore,
    )
    old = runtime.policy_active
    runtime.policy_draft = UpsPolicyDraft(25, 240)
    runtime.policy_status = "Pending changes"

    runtime._apply_policy()
    assert reloads.calls == 1
    store.break_next_policy_verify = True

    assert runtime.complete_policy_reload() is False

    assert runtime.policy_active == old
    assert runtime.policy_draft == old
    assert runtime.policy_revision == 4
    assert runtime.policy_hash == policy_hash(old)
    assert runtime.policy_status == "Apply failed"
    assert bridge.events == []
    persisted = store.load()
    assert persisted["policy_active"] == old.as_dict()
    assert persisted["policy_revision"] == 4
    assert runtime.policy_apply_store.load() == {}


def test_startup_rolls_back_interrupted_reload_requested_transaction(tmp_path):
    runtime, bridge, store, reloads = _runtime(tmp_path)
    old = runtime.policy_active
    runtime.policy_draft = UpsPolicyDraft(25, 240)
    runtime.policy_status = "Pending changes"
    runtime._apply_policy()
    assert reloads.calls == 1

    restarted = ShutdownAwareUpsRuntime(
        config=_config(),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.5.0",
        state_store=store,
        now_iso=lambda: "2026-09-16T01:01:00+05:00",
        now_monotonic=lambda: 101.0,
        reader=lambda config: parse_upsc_output("ups.status: OL\n"),
        capability_reader=lambda config: (_ for _ in ()).throw(RuntimeError("skip")),
        shutdown_policy_reader=lambda: (_ for _ in ()).throw(RuntimeError("skip")),
        shutdown_history_tracker=HistoryTracker(),
        shutdown_budget_reader=_budget,
        policy_reload_executor=reloads,
    )

    restarted._recover_interrupted_policy_apply()

    assert restarted.policy_active == old
    assert restarted.policy_draft == old
    assert restarted.policy_revision == 4
    assert restarted.policy_status == "Apply failed"
    assert restarted.policy_apply_store.load() == {}
