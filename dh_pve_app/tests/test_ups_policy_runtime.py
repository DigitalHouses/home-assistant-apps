import threading

from app.config import MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.state_store import StateStore
from app.ups_nut import parse_upsc_output
from app.ups_runtime import UpsRuntime
from app.ups_shutdown_policy import UpsShutdownPolicy


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


def _observed_policy():
    return UpsShutdownPolicy(
        state="Enabled",
        role="primary",
        nut_monitor="active",
        shutdown_enabled=True,
        shutdown_command="/sbin/shutdown -h now",
        min_supplies=1,
        pollfreq_seconds=5,
        pollfreqalert_seconds=5,
        deadtime_seconds=15,
        hostsync_seconds=120,
        finaldelay_seconds=5,
        upssched_present=True,
        upssched_rules=2,
        upssched_active=True,
        guest_shutdown_budget_seconds=280,
        power_restore_behavior="native",
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
    )


def test_runtime_publishes_effective_read_only_shutdown_policy(tmp_path):
    bridge = Bridge()
    snapshot = parse_upsc_output(
        "ups.status: OL\nbattery.charge: 100\nups.delay.start: 120\n"
    )
    runtime = UpsRuntime(
        config=_config(),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.2.0",
        state_store=StateStore(tmp_path / "ups.json"),
        now_iso=lambda: "2026-09-13T06:00:00+05:00",
        now_monotonic=lambda: 100.0,
        reader=lambda config: snapshot,
        capability_reader=lambda config: (_ for _ in ()).throw(RuntimeError("skip")),
        shutdown_policy_reader=_observed_policy,
    )

    assert runtime.policy_applier is None
    assert runtime.startup() is True

    observed = bridge.states[-1]["shutdown_policy"]
    assert observed["state"] == "Enabled"
    assert observed["role"] == "primary"
    assert observed["on_battery_delay_minutes"] == 30
    assert observed["power_restore_delay_seconds"] == 120
    assert observed["guest_shutdown_budget_seconds"] == 280


def test_runtime_bridge_has_no_policy_apply_or_draft_events(tmp_path):
    bridge = Bridge()
    snapshot = parse_upsc_output("ups.status: OL\nbattery.charge: 100\n")
    runtime = UpsRuntime(
        config=_config(),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.2.0",
        state_store=StateStore(tmp_path / "ups.json"),
        now_iso=lambda: "2026-09-13T06:00:00+05:00",
        now_monotonic=lambda: 100.0,
        reader=lambda config: snapshot,
        capability_reader=lambda config: (_ for _ in ()).throw(RuntimeError("skip")),
        shutdown_policy_reader=_observed_policy,
    )

    assert not hasattr(bridge, "ups_policy_updates")
    assert not hasattr(bridge, "ups_policy_apply_requested")
    assert runtime.policy_applier is None
    assert runtime.process_events() is False
