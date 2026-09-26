import threading

from app.config import MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.shutdown_integration import ShutdownAwareUpsRuntime
from app.state_store import StateStore
from app.ups_nut import parse_upsc_output
from app.ups_policy import UpsPolicyDraft
from app.ups_shutdown_budget import ShutdownBudgetInputs, calculate_shutdown_budget


class Bridge:
    def __init__(self):
        self.ups_refresh_requested = threading.Event()
        self.ups_reconnect_requested = threading.Event()
        self.ups_test_quick_requested = threading.Event()
        self.ups_test_deep_requested = threading.Event()
        self.ups_test_stop_requested = threading.Event()
        self.states = []
        self.discovery = []
        self.availability = []

    def publish_ups_state(self, payload):
        self.states.append(payload)
        return True

    def publish_ups_discovery(self, payload):
        self.discovery.append(payload)
        return True

    def publish_ups_availability(self, online):
        self.availability.append(online)
        return True


class HistoryTracker:
    def __init__(self):
        self.fingerprints = []
        self.commits = []

    def observe_ups(self, snapshot):
        return None

    def record_shutdown_budget_fingerprint(self, fingerprint):
        self.fingerprints.append(fingerprint)

    def record_software_shutdown_commit(self, reason, snapshot):
        self.commits.append((reason, snapshot.status_raw))

    def payload(self):
        return {
            "current_boot": None,
            "previous_shutdown": None,
            "history": [],
            "history_count": 0,
        }


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
        poll_interval_seconds=10.0,
        command_timeout_seconds=3.0,
    )


def _budget(fingerprint="budget-a"):
    base = calculate_shutdown_budget(
        ShutdownBudgetInputs(
            configured_guest_budget_seconds=280,
            observed_guest_budget_seconds=None,
            hostsync_seconds=120,
            hostsync_applicable=True,
            finaldelay_seconds=5,
            observed_host_tail_seconds=None,
            host_tail_fallback_seconds=90,
        )
    )
    return type(base)(
        **{
            **base.__dict__,
            "configuration_fingerprint": fingerprint,
        }
    )


def _runtime(tmp_path, *, snapshot, budget_reader, executor, clock, tracker):
    store = StateStore(tmp_path / "ups.json")
    policy = UpsPolicyDraft(20, 180)
    store.save(
        {
            "policy_active": policy.as_dict(),
            "policy_draft": policy.as_dict(),
            "policy_status": "Active",
            "policy_revision": 1,
        }
    )
    return ShutdownAwareUpsRuntime(
        config=_config(),
        mqtt_config=_mqtt(),
        bridge=Bridge(),
        identity=_identity(),
        version="0.2.0",
        state_store=store,
        now_iso=lambda: "2026-09-16T01:00:00+05:00",
        now_monotonic=lambda: clock["value"],
        reader=lambda config: snapshot,
        capability_reader=lambda config: (_ for _ in ()).throw(RuntimeError("skip")),
        shutdown_policy_reader=lambda: (_ for _ in ()).throw(RuntimeError("skip")),
        shutdown_history_tracker=tracker,
        shutdown_budget_reader=budget_reader,
        software_shutdown_executor=executor,
    )


def test_budget_reader_is_cached_for_60_seconds_but_manual_refresh_forces_refresh(tmp_path):
    clock = {"value": 100.0}
    tracker = HistoryTracker()
    calls = []

    def budget_reader():
        calls.append(clock["value"])
        return _budget(f"budget-{len(calls)}")

    runtime = _runtime(
        tmp_path,
        snapshot=parse_upsc_output(
            "ups.status: OB DISCHRG\nbattery.charge: 80\nbattery.runtime: 9999\n"
        ),
        budget_reader=budget_reader,
        executor=lambda reason: None,
        clock=clock,
        tracker=tracker,
    )

    runtime.startup()
    assert calls == [100.0]
    assert tracker.fingerprints == ["budget-1"]

    clock["value"] = 120.0
    runtime._collect(force=True)
    assert calls == [100.0]

    clock["value"] = 130.0
    runtime.manual_refresh()
    assert calls == [100.0, 130.0]
    assert tracker.fingerprints[-1] == "budget-2"

    clock["value"] = 185.0
    runtime._collect(force=True)
    assert calls == [100.0, 130.0]

    clock["value"] = 191.0
    runtime._collect(force=True)
    assert calls == [100.0, 130.0, 191.0]


def test_shutdown_history_is_recorded_only_after_executor_success(tmp_path):
    clock = {"value": 100.0}
    tracker = HistoryTracker()
    calls = []

    def executor(reason):
        calls.append(reason)
        if len(calls) == 1:
            raise RuntimeError("helper failed")

    runtime = _runtime(
        tmp_path,
        snapshot=parse_upsc_output(
            "ups.status: OB DISCHRG\nbattery.charge: 19\nbattery.runtime: 9999\n"
        ),
        budget_reader=lambda: _budget(),
        executor=executor,
        clock=clock,
        tracker=tracker,
    )

    runtime.startup()
    assert calls == ["charge_guard"]
    assert tracker.commits == []
    assert runtime.software_shutdown_committed is False

    clock["value"] = 110.0
    runtime._collect(force=True)

    assert calls == ["charge_guard", "charge_guard"]
    assert tracker.commits == [("charge_guard", "OB DISCHRG")]
    assert runtime.software_shutdown_committed is True

    clock["value"] = 120.0
    runtime._collect(force=True)
    assert tracker.commits == [("charge_guard", "OB DISCHRG")]
