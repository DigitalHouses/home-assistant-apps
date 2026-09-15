import threading

from app.config import MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.state_store import StateStore
from app.ups_nut import parse_upsc_output
from app.ups_policy import UpsPolicyDraft
from app.ups_runtime import UpsRuntime
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


def _budget(available=True):
    return calculate_shutdown_budget(
        ShutdownBudgetInputs(
            configured_guest_budget_seconds=280 if available else None,
            observed_guest_budget_seconds=None,
            hostsync_seconds=120,
            hostsync_applicable=True,
            finaldelay_seconds=5,
            observed_host_tail_seconds=None,
            host_tail_fallback_seconds=90,
        )
    )


def _runtime(tmp_path, snapshots, *, active=True, budget=None, executor=None):
    state_store = StateStore(tmp_path / "ups.json")
    if active:
        policy = UpsPolicyDraft(20, 180)
        state_store.save(
            {
                "policy_active": policy.as_dict(),
                "policy_draft": policy.as_dict(),
                "policy_status": "Active",
                "policy_revision": 1,
            }
        )
    iterator = iter(snapshots)
    last = snapshots[-1]

    def reader(config):
        nonlocal iterator
        try:
            return next(iterator)
        except StopIteration:
            return last

    return UpsRuntime(
        config=_config(),
        mqtt_config=_mqtt(),
        bridge=Bridge(),
        identity=_identity(),
        version="0.2.0",
        state_store=state_store,
        now_iso=lambda: "2026-09-16T01:00:00+05:00",
        now_monotonic=lambda: 100.0,
        reader=reader,
        capability_reader=lambda config: (_ for _ in ()).throw(RuntimeError("skip")),
        shutdown_policy_reader=lambda: (_ for _ in ()).throw(RuntimeError("skip")),
        shutdown_budget_reader=lambda: budget if budget is not None else _budget(),
        software_shutdown_executor=executor,
    )


def _snapshot(status, charge, runtime):
    return parse_upsc_output(
        f"ups.status: {status}\nbattery.charge: {charge}\nbattery.runtime: {runtime}\n"
    )


def test_runtime_commits_charge_guard_once_after_successful_ups_poll(tmp_path):
    calls = []
    runtime = _runtime(
        tmp_path,
        [_snapshot("OB", 20, 9999), _snapshot("OB", 19, 9999)],
        executor=lambda reason: calls.append(reason),
    )

    assert runtime.startup() is True
    assert calls == ["charge_guard"]
    runtime.manual_refresh()
    assert calls == ["charge_guard"]
    assert runtime.software_shutdown_committed is True
    assert runtime.software_shutdown_reason == "charge_guard"


def test_runtime_uses_runtime_guard_when_charge_guard_is_not_met(tmp_path):
    calls = []
    runtime = _runtime(
        tmp_path,
        [_snapshot("OB", 80, 675)],
        executor=lambda reason: calls.append(reason),
    )

    runtime.startup()

    assert calls == ["runtime_guard"]
    assert runtime.software_shutdown_reason == "runtime_guard"


def test_runtime_without_active_v2_policy_never_executes_shutdown(tmp_path):
    calls = []
    runtime = _runtime(
        tmp_path,
        [_snapshot("OB", 1, 1)],
        active=False,
        executor=lambda reason: calls.append(reason),
    )

    runtime.startup()

    assert calls == []
    assert runtime.software_shutdown_committed is False


def test_unavailable_budget_disables_runtime_guard_but_not_charge_guard(tmp_path):
    calls = []
    runtime = _runtime(
        tmp_path,
        [_snapshot("OB", 80, 1), _snapshot("OB", 20, 1)],
        budget=_budget(False),
        executor=lambda reason: calls.append(reason),
    )

    runtime.startup()
    assert calls == []
    runtime.manual_refresh()
    assert calls == ["charge_guard"]


def test_executor_failure_does_not_crash_collection_or_latch_and_retries(tmp_path):
    calls = []

    def executor(reason):
        calls.append(reason)
        if len(calls) == 1:
            raise RuntimeError("FSD helper failed")

    runtime = _runtime(
        tmp_path,
        [_snapshot("OB", 80, 1), _snapshot("OB", 80, 1)],
        executor=executor,
    )

    assert runtime.startup() is True
    assert runtime.software_shutdown_committed is False
    runtime.manual_refresh()
    assert calls == ["runtime_guard", "runtime_guard"]
    assert runtime.software_shutdown_committed is True


def test_online_or_native_lb_only_sample_does_not_call_software_executor(tmp_path):
    calls = []
    runtime = _runtime(
        tmp_path,
        [_snapshot("OL", 1, 1), _snapshot("OB LB", 80, 9999)],
        executor=lambda reason: calls.append(reason),
    )

    runtime.startup()
    runtime.manual_refresh()

    assert calls == []
