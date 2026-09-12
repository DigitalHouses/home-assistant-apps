import queue
import threading

from app.config import MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.mqtt_bridge import PolicyDraftUpdate
from app.state_store import StateStore
from app.ups_nut import parse_upsc_output
from app.ups_policy import PolicyApplyResult, PolicySafetyFacts, UpsPolicyDraft, policy_hash
from app.ups_runtime import UpsRuntime


class Bridge:
    def __init__(self):
        self.ups_refresh_requested = threading.Event()
        self.ups_reconnect_requested = threading.Event()
        self.ups_test_quick_requested = threading.Event()
        self.ups_test_deep_requested = threading.Event()
        self.ups_test_stop_requested = threading.Event()
        self.ups_policy_apply_requested = threading.Event()
        self.ups_policy_updates = queue.SimpleQueue()
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


def _config(*, policy_apply_enabled=False):
    return UpsConfig(
        enabled=True,
        name="ups",
        host="127.0.0.1",
        port=3493,
        poll_interval_seconds=5.0,
        command_timeout_seconds=3.0,
        policy_apply_enabled=policy_apply_enabled,
    )


def _facts():
    return PolicySafetyFacts(
        guest_shutdown_budget_seconds=280,
        hostsync_seconds=120,
        finaldelay_seconds=5,
        host_shutdown_reserve_seconds=60,
        ups_poweroff_delay_seconds=60,
        safety_margin_seconds=60,
    )


def _runtime(
    tmp_path,
    *,
    applier,
    facts_reader=_facts,
    state_path=None,
    policy_apply_enabled=False,
):
    bridge = Bridge()
    clock = {"iso": "2026-09-13T00:30:00+05:00", "mono": 100.0}
    snapshot = parse_upsc_output("ups.status: OL\nbattery.charge: 100\n")
    store = StateStore(state_path or (tmp_path / "ups.json"))
    runtime = UpsRuntime(
        config=_config(policy_apply_enabled=policy_apply_enabled),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.2.0",
        state_store=store,
        now_iso=lambda: clock["iso"],
        now_monotonic=lambda: clock["mono"],
        reader=lambda config: snapshot,
        policy_facts_reader=facts_reader,
        policy_applier=applier,
    )
    return bridge, runtime, clock, store


def test_commissioning_starts_with_safe_draft_and_no_active_policy(tmp_path):
    bridge, runtime, _clock, _store = _runtime(
        tmp_path,
        applier=lambda draft, facts: PolicyApplyResult(True, "unused"),
    )

    runtime.startup()
    policy = bridge.states[-1]["policy"]

    assert policy["status"] == "Commissioning"
    assert policy["apply_enabled"] is False
    assert policy["draft"] == {
        "on_battery_delay_minutes": 30,
        "power_restore_delay_seconds": 120,
    }
    assert policy["active"] is None
    assert policy["last_applied"] is None
    assert policy["policy_revision"] == 0
    assert policy["policy_hash"] is None
    assert "minimum_emergency_runtime_reserve_seconds" not in policy
    assert "recommended_emergency_runtime_reserve_seconds" not in policy


def test_policy_payload_reports_when_local_apply_gate_is_enabled(tmp_path):
    bridge, runtime, _clock, _store = _runtime(
        tmp_path,
        applier=lambda draft, facts: PolicyApplyResult(True, "unused"),
        policy_apply_enabled=True,
    )

    runtime.startup()

    assert bridge.states[-1]["policy"]["apply_enabled"] is True


def test_draft_change_sets_pending_and_never_calls_applier(tmp_path):
    calls = []

    def applier(draft, facts):
        calls.append((draft, facts))
        return PolicyApplyResult(True, "should not run")

    bridge, runtime, _clock, _store = _runtime(tmp_path, applier=applier)
    runtime.startup()
    bridge.states.clear()
    bridge.ups_policy_updates.put(
        PolicyDraftUpdate(key="on_battery_delay_minutes", value=35)
    )

    assert runtime.process_events() is True

    assert calls == []
    assert runtime.policy_draft.on_battery_delay_minutes == 35
    assert runtime.policy_active is None
    assert runtime.policy_status == "Pending changes"
    assert bridge.states[-1]["policy"]["draft"]["on_battery_delay_minutes"] == 35
    assert bridge.states[-1]["policy"]["status"] == "Pending changes"


def test_successful_apply_promotes_snapshot_and_sets_timestamp_revision_hash(tmp_path):
    captured = []

    def applier(draft, facts):
        captured.append(draft)
        return PolicyApplyResult(True, "Политика применена.")

    bridge, runtime, clock, store = _runtime(tmp_path, applier=applier)
    runtime.startup()
    bridge.ups_policy_updates.put(
        PolicyDraftUpdate(key="on_battery_delay_minutes", value=35)
    )
    runtime.process_events()
    clock["iso"] = "2026-09-13T00:35:00+05:00"
    bridge.ups_policy_apply_requested.set()

    assert runtime.process_events() is True

    expected = UpsPolicyDraft(35, 120)
    assert captured == [expected]
    assert runtime.policy_active == expected
    assert runtime.policy_draft == expected
    assert runtime.policy_status == "Active"
    assert runtime.policy_apply_result == "Политика применена."
    assert runtime.policy_last_applied == "2026-09-13T00:35:00+05:00"
    assert runtime.policy_revision == 1
    assert runtime.policy_hash == policy_hash(expected)

    state = bridge.states[-1]["policy"]
    assert state["active"] == expected.as_dict()
    assert state["policy_revision"] == 1
    assert state["policy_hash"] == policy_hash(expected)
    assert state["last_applied"] == "2026-09-13T00:35:00+05:00"

    persisted = store.load()
    assert persisted["policy_active"] == expected.as_dict()
    assert persisted["policy_revision"] == 1
    assert persisted["policy_last_applied"] == "2026-09-13T00:35:00+05:00"


def test_validation_failure_keeps_active_and_timestamp_and_reverts_draft(tmp_path):
    calls = []
    facts = {"value": _facts()}

    def facts_reader():
        return facts["value"]

    def applier(draft, safety):
        calls.append(draft)
        return PolicyApplyResult(True, "Политика применена.")

    bridge, runtime, clock, _store = _runtime(
        tmp_path, applier=applier, facts_reader=facts_reader
    )
    runtime.startup()
    bridge.ups_policy_apply_requested.set()
    assert runtime.process_events() is True
    assert len(calls) == 1
    first_active = runtime.policy_active
    first_time = runtime.policy_last_applied
    first_hash = runtime.policy_hash

    bridge.ups_policy_updates.put(
        PolicyDraftUpdate(key="on_battery_delay_minutes", value=35)
    )
    runtime.process_events()
    facts["value"] = PolicySafetyFacts(
        guest_shutdown_budget_seconds=-1,
        hostsync_seconds=120,
        finaldelay_seconds=5,
        host_shutdown_reserve_seconds=60,
        ups_poweroff_delay_seconds=60,
        safety_margin_seconds=60,
    )
    clock["iso"] = "2026-09-13T00:50:00+05:00"
    bridge.ups_policy_apply_requested.set()

    assert runtime.process_events() is True

    assert len(calls) == 1
    assert runtime.policy_active == first_active
    assert runtime.policy_draft == first_active
    assert runtime.policy_status == "Validation failed"
    assert "guest_shutdown_budget_seconds" in runtime.policy_apply_result
    assert runtime.policy_last_applied == first_time
    assert runtime.policy_revision == 1
    assert runtime.policy_hash == first_hash
    assert bridge.states[-1]["policy"]["draft"] == first_active.as_dict()


def test_apply_failure_keeps_previous_active_and_reverts_draft(tmp_path):
    fail = {"value": False}

    def applier(draft, facts):
        if fail["value"]:
            return PolicyApplyResult(False, "Проверка применённой конфигурации не прошла.")
        return PolicyApplyResult(True, "Политика применена.")

    bridge, runtime, clock, _store = _runtime(tmp_path, applier=applier)
    runtime.startup()
    bridge.ups_policy_apply_requested.set()
    runtime.process_events()
    first_active = runtime.policy_active
    first_time = runtime.policy_last_applied
    first_hash = runtime.policy_hash

    bridge.ups_policy_updates.put(
        PolicyDraftUpdate(key="on_battery_delay_minutes", value=35)
    )
    runtime.process_events()
    fail["value"] = True
    clock["iso"] = "2026-09-13T01:00:00+05:00"
    bridge.ups_policy_apply_requested.set()

    assert runtime.process_events() is True

    assert runtime.policy_active == first_active
    assert runtime.policy_draft == first_active
    assert runtime.policy_status == "Apply failed"
    assert "не прошла" in runtime.policy_apply_result
    assert runtime.policy_last_applied == first_time
    assert runtime.policy_revision == 1
    assert runtime.policy_hash == first_hash


def test_persisted_active_policy_survives_runtime_restart_and_reconnect(tmp_path):
    path = tmp_path / "ups.json"

    def applier(draft, facts):
        return PolicyApplyResult(True, "Политика применена.")

    bridge, runtime, _clock, _store = _runtime(
        tmp_path, applier=applier, state_path=path
    )
    runtime.startup()
    bridge.ups_policy_apply_requested.set()
    runtime.process_events()

    bridge2, runtime2, _clock2, _store2 = _runtime(
        tmp_path, applier=applier, state_path=path
    )
    runtime2.startup()
    bridge2.states.clear()

    assert runtime2.republish_after_reconnect() is True
    policy = bridge2.states[-1]["policy"]
    assert policy["status"] == "Active"
    assert policy["active"] == {
        "on_battery_delay_minutes": 30,
        "power_restore_delay_seconds": 120,
    }
    assert policy["policy_revision"] == 1
    assert policy["policy_hash"] is not None
    assert policy["last_applied"] is not None


def test_legacy_persisted_policy_with_runtime_reserve_is_migrated_read_only(tmp_path):
    path = tmp_path / "ups.json"
    store = StateStore(path)
    store.save(
        {
            "policy_active": {
                "on_battery_delay_minutes": 30,
                "emergency_runtime_reserve_minutes": 15,
                "power_restore_delay_seconds": 120,
            },
            "policy_draft": {
                "on_battery_delay_minutes": 35,
                "emergency_runtime_reserve_minutes": 20,
                "power_restore_delay_seconds": 150,
            },
            "policy_status": "Pending changes",
            "policy_revision": 2,
        }
    )

    _bridge, runtime, _clock, _store = _runtime(
        tmp_path,
        applier=lambda draft, facts: PolicyApplyResult(True, "unused"),
        state_path=path,
    )

    assert runtime.policy_active == UpsPolicyDraft(30, 120)
    assert runtime.policy_draft == UpsPolicyDraft(35, 150)
    assert "emergency_runtime_reserve_minutes" not in runtime.policy_draft.as_dict()
