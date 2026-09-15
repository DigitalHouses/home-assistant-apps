import threading

from app.config import MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.state_store import StateStore
from app.ups_nut import parse_upsc_output
from app.ups_policy import UpsPolicyDraft, policy_hash
from app.ups_runtime import UpsRuntime


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


def _runtime(tmp_path, persisted=None):
    state_store = StateStore(tmp_path / "ups.json")
    if persisted is not None:
        state_store.save(persisted)
    snapshot = parse_upsc_output("ups.status: OL\nbattery.charge: 100\n")
    return UpsRuntime(
        config=_config(),
        mqtt_config=_mqtt(),
        bridge=Bridge(),
        identity=_identity(),
        version="0.2.0",
        state_store=state_store,
        now_iso=lambda: "2026-09-16T01:00:00+05:00",
        now_monotonic=lambda: 100.0,
        reader=lambda config: snapshot,
        capability_reader=lambda config: (_ for _ in ()).throw(RuntimeError("skip")),
    )


def test_legacy_v1_policy_is_not_silently_promoted_to_active_v2(tmp_path):
    runtime = _runtime(
        tmp_path,
        {
            "policy_active": {
                "on_battery_delay_minutes": 30,
                "power_restore_delay_seconds": 120,
            },
            "policy_draft": {
                "on_battery_delay_minutes": 45,
                "power_restore_delay_seconds": 180,
            },
            "policy_status": "Active",
            "policy_revision": 7,
            "policy_hash": "legacy-hash",
            "policy_last_applied": "2026-09-15T10:00:00+05:00",
        },
    )

    assert runtime.policy_active is None
    assert runtime.policy_draft == UpsPolicyDraft(20, 180)
    assert runtime.policy_status == "Legacy policy"
    assert runtime.policy_revision == 0
    assert runtime.policy_hash is None
    assert runtime.policy_last_applied is None


def test_persisted_v2_active_policy_is_restored_without_revision_loss(tmp_path):
    active = UpsPolicyDraft(25, 300)
    runtime = _runtime(
        tmp_path,
        {
            "policy_active": active.as_dict(),
            "policy_draft": active.as_dict(),
            "policy_status": "Active",
            "policy_revision": 8,
            "policy_last_applied": "2026-09-16T00:30:00+05:00",
        },
    )

    assert runtime.policy_active == active
    assert runtime.policy_draft == active
    assert runtime.policy_status == "Active"
    assert runtime.policy_revision == 8
    assert runtime.policy_hash == policy_hash(active)
    assert runtime.policy_last_applied == "2026-09-16T00:30:00+05:00"
