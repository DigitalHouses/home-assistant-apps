import queue
import threading

from app.config import MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.state_store import StateStore
from app.ups_nut import NutReadError, parse_upsc_output
from app.ups_runtime import UpsRuntime


class Bridge:
    def __init__(self):
        self.ups_refresh_requested = threading.Event()
        self.ups_reconnect_requested = threading.Event()
        self.setting_updates = queue.SimpleQueue()
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


def _runtime(tmp_path, reader):
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
        mqtt_config=MqttConfig(
            host="mqtt",
            port=1883,
            username="",
            password="",
            topic_prefix="DigitalHouses/Global/dh_pve_app",
            discovery_prefix="homeassistant",
            keepalive_seconds=60,
        ),
        bridge=bridge,
        identity=HostIdentity(
            machine_id="0123456789abcdef0123456789abcdef",
            instance_id="node_a",
            hostname="pve",
            node_name="PVE",
        ),
        version="0.2.0-alpha",
        state_store=StateStore(tmp_path / "ups.json"),
        now_iso=lambda: "2026-09-12T03:00:00+00:00",
        now_monotonic=lambda: 100.0,
        reader=reader,
    )
    return bridge, runtime


def test_success_state_contains_python_problem_summary(tmp_path):
    snapshot = parse_upsc_output("ups.status: OL\nbattery.charge: 100\n")
    bridge, runtime = _runtime(tmp_path, lambda config: snapshot)

    assert runtime.startup() is True
    state = bridge.states[-1]

    assert state["problems_count"] == 0
    assert state["problems_severity"] == "ok"
    assert state["problems"] == []
    assert state["problems_details"] == "Проблем не обнаружено."


def test_problem_state_contains_all_active_problems(tmp_path):
    snapshot = parse_upsc_output("ups.status: OB LB DISCHRG\n")
    bridge, runtime = _runtime(tmp_path, lambda config: snapshot)

    assert runtime.startup() is True
    state = bridge.states[-1]

    assert state["problems_count"] == 2
    assert state["problems_severity"] == "critical"
    assert state["problems"] == [
        "ИБП работает от батареи.",
        "Низкий заряд батареи.",
    ]


def test_nut_failure_still_publishes_critical_problem_summary(tmp_path):
    def reader(config):
        raise NutReadError("NUT недоступен")

    bridge, runtime = _runtime(tmp_path, reader)

    assert runtime.startup() is False
    state = bridge.states[-1]

    assert state["available"] is False
    assert state["problems_count"] == 1
    assert state["problems_severity"] == "critical"
    assert state["problems"] == ["Данные ИБП через NUT недоступны."]
