from app.config import MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.shutdown_discovery import build_shutdown_aware_ups_discovery_payload
from app.state_store import StateStore
from app.ups_nut import parse_upsc_output
from app.ups_runtime import UpsRuntime


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


def _runtime(tmp_path, *, poll_interval_seconds=5.0):
    snapshot = parse_upsc_output("ups.status: OL\nbattery.runtime: 2160\n")
    bridge = Bridge()
    runtime = UpsRuntime(
        config=UpsConfig(
            enabled=True,
            name="ups",
            host="127.0.0.1",
            port=3493,
            poll_interval_seconds=poll_interval_seconds,
            command_timeout_seconds=3.0,
        ),
        mqtt_config=_mqtt(),
        bridge=bridge,
        identity=_identity(),
        version="0.2.0-alpha",
        state_store=StateStore(tmp_path / "ups.json"),
        now_iso=lambda: "2026-09-12T04:00:00+00:00",
        now_monotonic=lambda: 100.0,
        reader=lambda config: snapshot,
    )
    return runtime, bridge


def test_runtime_minutes_are_published_by_python(tmp_path):
    runtime, bridge = _runtime(tmp_path)

    assert runtime.startup() is True
    assert bridge.states[-1]["runtime_seconds"] == 2160.0
    assert bridge.states[-1]["battery_runtime_minutes"] == 36.0


def test_ups_runtime_uses_fixed_10_second_collection_even_for_legacy_config_value(tmp_path):
    runtime, _bridge = _runtime(tmp_path, poll_interval_seconds=1.0)

    assert runtime.scheduler.interval("ups") == 10.0


def test_production_discovery_exposes_minutes_without_duplicate_seconds_entity():
    snapshot = parse_upsc_output("ups.status: OL\nbattery.runtime: 2160\n")
    components = build_shutdown_aware_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=snapshot
    )["components"]

    minutes = components["battery_runtime_minutes"]
    assert minutes["default_entity_id"] == "sensor.dh_pve_agent_ups_battery_runtime_minutes"
    assert minutes["value_template"] == "{{ value_json.battery_runtime_minutes }}"
    assert minutes["unit_of_measurement"] == "min"
    assert minutes["device_class"] == "duration"
    assert minutes.get("entity_category") is None
    assert "battery_runtime" not in components
