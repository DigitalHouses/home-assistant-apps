from types import SimpleNamespace

from app.config import MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.shutdown_discovery import build_shutdown_aware_ups_discovery_payload
from app.shutdown_integration import ShutdownAwareUpsRuntime
from app.state_store import StateStore
from app.topics import build_ups_topics, ups_state_group_topic
from app.ups_nut import parse_upsc_output
from app.ups_shutdown_budget import ShutdownBudgetInputs, calculate_shutdown_budget


class Bridge:
    def __init__(self):
        import threading

        self.ups_refresh_requested = threading.Event()
        self.ups_reconnect_requested = threading.Event()
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


class GroupBridge(Bridge):
    def __init__(self):
        super().__init__()
        self.group_states = []

    def publish_ups_state_group(self, group, payload):
        self.group_states.append((group, payload))
        return True


class Tracker:
    def observe_ups(self, snapshot):
        return None

    def payload(self):
        return {
            "current_boot": None,
            "previous_shutdown": None,
            "history": [],
            "history_count": 0,
        }

    def record_shutdown_budget_fingerprint(self, fingerprint):
        return None


def mqtt_config():
    return MqttConfig(
        host="mqtt",
        port=1883,
        username="",
        password="",
        topic_prefix="DigitalHouses/Global/dh_pve_app",
        discovery_prefix="homeassistant",
        keepalive_seconds=60,
    )


def identity():
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )


def shutdown_policy():
    return SimpleNamespace(
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
        guest_shutdown_budget_seconds=None,
        power_restore_behavior="Not configured",
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
        as_dict=lambda: {
            "state": "Enabled",
            "role": "primary",
            "nut_monitor": "active",
            "shutdown_enabled": True,
            "hostsync_seconds": 120,
            "finaldelay_seconds": 5,
            "guest_shutdown_budget_seconds": None,
        },
    )


def budget():
    return calculate_shutdown_budget(
        ShutdownBudgetInputs(
            configured_guest_budget_seconds=420,
            observed_guest_budget_seconds=None,
            hostsync_seconds=120,
            hostsync_applicable=True,
            finaldelay_seconds=5,
            observed_host_tail_seconds=None,
            host_tail_fallback_seconds=90,
        )
    )


def runtime(tmp_path, bridge):
    snapshot = parse_upsc_output("ups.status: OL\nbattery.charge: 100\nbattery.runtime: 5790\n")
    return ShutdownAwareUpsRuntime(
        config=UpsConfig(enabled=True, name="ups", host="127.0.0.1", port=3493),
        mqtt_config=mqtt_config(),
        bridge=bridge,
        identity=identity(),
        version="0.3.0",
        state_store=StateStore(tmp_path / "ups.json"),
        now_iso=lambda: "2026-09-16T04:30:00+05:00",
        now_monotonic=lambda: 100.0,
        reader=lambda config: snapshot,
        capability_reader=lambda config: SimpleNamespace(
            as_dict=lambda: {
                "available": True,
                "count": 0,
                "commands": [],
                "battery_tests": [],
                "beeper_control": False,
                "load_control": False,
                "shutdown_control": False,
                "supported_features": [],
            }
        ),
        shutdown_policy_reader=shutdown_policy,
        shutdown_history_tracker=Tracker(),
        shutdown_budget_reader=budget,
    )


def test_runtime_publishes_full_shutdown_budget_object_and_correct_readiness(tmp_path):
    bridge = Bridge()
    app = runtime(tmp_path, bridge)

    assert app.startup() is True
    state = bridge.states[-1]

    assert state["shutdown_budget"]["effective_guest_budget_seconds"] == 420
    assert state["shutdown_budget"]["shutdown_budget_seconds"] == 635
    assert state["shutdown_readiness"]["guest_shutdown_budget_seconds"] == 420
    assert state["shutdown_readiness"]["shutdown_budget_seconds"] == 635


def test_grouped_runtime_publishes_shutdown_budget_in_diagnostics(tmp_path):
    bridge = GroupBridge()
    app = runtime(tmp_path, bridge)

    assert app.startup() is True
    groups = {group: payload for group, payload in bridge.group_states}
    diagnostics = groups["diagnostics"]

    assert diagnostics["shutdown_budget"]["effective_guest_budget_seconds"] == 420
    assert diagnostics["shutdown_budget"]["shutdown_budget_seconds"] == 635


def test_discovery_exposes_separate_guest_and_total_budget_sensors():
    components = build_shutdown_aware_ups_discovery_payload(
        mqtt_config(),
        identity(),
        version="0.3.0",
        snapshot=parse_upsc_output("ups.status: OL\n"),
    )["components"]
    topics = build_ups_topics(mqtt_config(), identity())
    diagnostics_topic = ups_state_group_topic(topics, "diagnostics")

    guest = components["guest_shutdown_budget"]
    total = components["shutdown_budget"]
    readiness = components["shutdown_readiness"]

    assert guest["default_entity_id"] == "sensor.dh_app_pve_ups_guest_shutdown_budget"
    assert guest["state_topic"] == diagnostics_topic
    assert "value_json.shutdown_budget.effective_guest_budget_seconds" in guest["value_template"]
    assert total["default_entity_id"] == "sensor.dh_app_pve_ups_shutdown_budget"
    assert total["state_topic"] == diagnostics_topic
    assert "value_json.shutdown_budget.shutdown_budget_seconds" in total["value_template"]
    assert "shutdown_budget_seconds" in readiness["json_attributes_template"]


def test_discovery_removes_legacy_on_battery_delay_but_keeps_restore_delay():
    components = build_shutdown_aware_ups_discovery_payload(
        mqtt_config(),
        identity(),
        version="0.3.0",
        snapshot=parse_upsc_output("ups.status: OL\n"),
    )["components"]

    assert "policy_on_battery_delay_observed" not in components
    assert "policy_power_restore_delay_observed" in components
