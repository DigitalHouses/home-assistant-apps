from app.config import MqttConfig, UpsConfig
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity
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
        topic_prefix="DigitalHouses/Global/dh_pve_app",
        discovery_prefix="homeassistant",
        keepalive_seconds=60,
    )


def test_runtime_minutes_are_published_by_python(tmp_path):
    snapshot = parse_upsc_output("ups.status: OL\nbattery.runtime: 2160\n")
    bridge = Bridge()
    runtime = UpsRuntime(
        config=UpsConfig(
            enabled=True,
            name="ups",
            host="127.0.0.1",
            port=3493,
            poll_interval_seconds=5.0,
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

    assert runtime.startup() is True
    assert bridge.states[-1]["runtime_seconds"] == 2160.0
    assert bridge.states[-1]["battery_runtime_minutes"] == 36.0


def test_discovery_exposes_minutes_and_keeps_seconds_as_diagnostic():
    snapshot = parse_upsc_output("ups.status: OL\nbattery.runtime: 2160\n")
    components = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=snapshot
    )["components"]

    minutes = components["battery_runtime_minutes"]
    assert minutes["default_entity_id"] == "sensor.dh_ups_battery_runtime_minutes"
    assert minutes["value_template"] == "{{ value_json.battery_runtime_minutes }}"
    assert minutes["unit_of_measurement"] == "min"
    assert minutes["device_class"] == "duration"
    assert minutes.get("entity_category") is None

    seconds = components["battery_runtime"]
    assert seconds["default_entity_id"] == "sensor.dh_ups_battery_runtime"
    assert seconds["unit_of_measurement"] == "s"
    assert seconds["entity_category"] == "diagnostic"
