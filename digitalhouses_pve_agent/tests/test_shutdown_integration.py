from __future__ import annotations

import json
from types import SimpleNamespace

from app.config import AppConfig, GeneralConfig, MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.shutdown_discovery import (
    build_shutdown_aware_pve_discovery_payload,
    build_shutdown_aware_ups_discovery_payload,
)
from app.shutdown_integration import ShutdownAwareTopologyManager, ShutdownAwareUpsRuntime
from app.state_store import StateStore
from app.ups_nut import parse_upsc_output


class _Runner:
    def __call__(self, argv, *, timeout=20.0, check=True):
        argv = tuple(argv)
        if argv == ("lspci", "-Dnn"):
            return ""
        if argv[:2] == ("qm", "agent"):
            return ""
        raise AssertionError(argv)


def _config_reader(kind: str, guest_id: str) -> str:
    if kind == "vm" and guest_id == "110":
        return "agent: enabled=1\nonboot: 1\nstartup: order=30,down=200\n"
    if kind == "lxc" and guest_id == "149":
        return "onboot: 1\nstartup: order=20,down=60\n"
    return ""


def _write_topology_cache(root) -> None:
    (root / ".vmlist").write_text(
        json.dumps(
            {
                "version": 1,
                "ids": {
                    "110": {"node": "pve", "type": "qemu", "version": 1},
                    "149": {"node": "pve", "type": "lxc", "version": 1},
                },
            }
        ),
        encoding="utf-8",
    )
    (root / ".rrd").write_text(
        "\n".join(
            [
                "pve2.3-vm/110:600:haos:running:0:100:4:0.1:4294967296:2147483648:34359738368:8589934592:1:2:3:4",
                "pve2.3-vm/149:600:climate:running:0:100:2:0.1:2147483648:1073741824:34359738368:8589934592:1:2:3:4",
            ]
        )
        + "\n",
        encoding="utf-8",
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


def _identity():
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )


def _app_config():
    return AppConfig(
        general=GeneralConfig(instance_id="", node_name="PVE", log_level="info"),
        mqtt=_mqtt(),
    )


def test_guest_payload_exposes_effective_shutdown_configuration(tmp_path):
    _write_topology_cache(tmp_path)
    manager = ShutdownAwareTopologyManager(
        runner=_Runner(),
        dri_to_pci={},
        config_reader=_config_reader,
        pve_root=tmp_path,
        node_name="pve",
        now_epoch=lambda: 110.0,
    )
    manager.full_scan()

    payload = manager.guest_payload()

    assert payload["vms"]["110"]["shutdown_timeout_seconds"] == 200
    assert payload["vms"]["110"]["shutdown_order"] == 30
    assert payload["vms"]["110"]["onboot"] is True
    assert payload["lxcs"]["149"]["shutdown_timeout_seconds"] == 60
    assert payload["lxcs"]["149"]["shutdown_order"] == 20


def test_guest_discovery_exposes_previous_shutdown_and_per_guest_duration_attributes():
    inventory = {
        "host": {
            "hostname": "pve",
            "shutdown_history": {
                "history_count": 1,
                "history": [{"shutdown_class": "ups_power"}],
                "previous_shutdown": {
                    "shutdown_class": "ups_power",
                    "shutdown_reason": "on_battery_fsd",
                    "shutdown_at": "2026-09-13T23:09:09+05:00",
                    "guest_shutdown_total_seconds": 140,
                    "guests": {
                        "vm": {
                            "110": {
                                "duration_seconds": 62,
                                "timeout_seconds": 60,
                                "timeout_ratio": 1.033,
                                "result": "timeout",
                                "forced": True,
                            }
                        },
                        "lxc": {},
                    },
                },
            },
        },
        "guests": {
            "vms": {
                "110": {
                    "kind": "vm",
                    "guest_id": "110",
                    "name": "haos",
                    "status": "running",
                    "qemu_agent": "available",
                    "passthrough_count": 0,
                    "shutdown_timeout_seconds": 200,
                    "shutdown_order": 30,
                    "onboot": True,
                }
            },
            "lxcs": {},
            "summary": {"vms": {"running": 1, "total": 1}, "lxcs": {"running": 0, "total": 0}},
        },
    }

    components = build_shutdown_aware_pve_discovery_payload(
        _app_config(), _identity(), version="0.2.0-alpha", inventory=inventory
    )["components"]

    previous = components["previous_shutdown"]
    assert previous["default_entity_id"] == "sensor.dh_pve_agent_previous_shutdown"
    assert "shutdown_reason" in previous["json_attributes_template"]
    assert "shutdown_clean" in previous["json_attributes_template"]
    assert "guest_shutdown_total_seconds" in previous["json_attributes_template"]

    history = components["shutdown_history"]
    assert history["default_entity_id"] == "sensor.dh_pve_agent_shutdown_history"
    assert "history" in history["json_attributes_template"]

    haos = components["vm_110_shutdown"]
    attrs = haos["json_attributes_template"]
    assert haos["default_entity_id"] == "sensor.dh_pve_agent_vm_110_shutdown"
    assert "shutdown_timeout_seconds" in attrs
    assert "last_shutdown_duration_seconds" in attrs
    assert "last_shutdown_timeout_ratio" in attrs
    assert "last_shutdown_result" in attrs
    assert "last_shutdown_forced" in attrs


def test_ups_discovery_has_dedicated_budget_and_readiness_entities():
    snapshot = parse_upsc_output("ups.status: OL\n")
    components = build_shutdown_aware_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=snapshot
    )["components"]

    budget = components["guest_shutdown_budget"]
    assert budget["default_entity_id"] == "sensor.dh_pve_agent_ups_guest_shutdown_budget"
    assert budget["unit_of_measurement"] == "s"
    assert budget["device_class"] == "duration"
    assert "effective_guest_budget_seconds" in budget["value_template"]

    total_budget = components["shutdown_budget"]
    assert total_budget["default_entity_id"] == "sensor.dh_pve_agent_ups_shutdown_budget"
    assert "shutdown_budget_seconds" in total_budget["value_template"]

    readiness = components["shutdown_readiness"]
    assert readiness["default_entity_id"] == "sensor.dh_pve_agent_ups_shutdown_readiness"
    assert "value_json.shutdown_readiness.status" in readiness["value_template"]
    assert "issues" in readiness["json_attributes_template"]
    assert "shutdown_budget_seconds" in readiness["json_attributes_template"]


class _Bridge:
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


class _Tracker:
    def __init__(self):
        self.observed = []

    def observe_ups(self, snapshot):
        self.observed.append(snapshot.status_raw)

    def payload(self):
        return {
            "previous_shutdown": {
                "guests": {
                    "vm": {
                        "110": {
                            "duration_seconds": 62,
                            "timeout_seconds": 60,
                            "timeout_ratio": 1.033,
                            "result": "timeout",
                            "forced": True,
                        }
                    },
                    "lxc": {},
                }
            }
        }


def test_ups_runtime_records_fsd_and_publishes_readiness_and_budget(tmp_path):
    tracker = _Tracker()
    bridge = _Bridge()
    snapshot = parse_upsc_output("ups.status: OB FSD\nbattery.charge: 50\n")
    policy = SimpleNamespace(
        state="Enabled",
        role="primary",
        nut_monitor="active",
        shutdown_enabled=True,
        shutdown_command="/sbin/shutdown -h now",
        min_supplies=None,
        pollfreq_seconds=None,
        pollfreqalert_seconds=None,
        deadtime_seconds=None,
        hostsync_seconds=120,
        finaldelay_seconds=5,
        upssched_present=True,
        upssched_rules=2,
        upssched_active=True,
        guest_shutdown_budget_seconds=420,
        power_restore_behavior="120 s",
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
        as_dict=lambda: {
            "state": "Enabled",
            "role": "primary",
            "nut_monitor": "active",
            "shutdown_enabled": True,
            "shutdown_command": "/sbin/shutdown -h now",
            "min_supplies": None,
            "pollfreq_seconds": None,
            "pollfreqalert_seconds": None,
            "deadtime_seconds": None,
            "hostsync_seconds": 120,
            "finaldelay_seconds": 5,
            "upssched_present": True,
            "upssched_rules": 2,
            "upssched_active": True,
            "guest_shutdown_budget_seconds": 420,
            "power_restore_behavior": "120 s",
            "on_battery_delay_minutes": 30,
            "power_restore_delay_seconds": 120,
        },
    )
    runtime = ShutdownAwareUpsRuntime(
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
        now_iso=lambda: "2026-09-14T01:00:00+05:00",
        now_monotonic=lambda: 100.0,
        reader=lambda config: snapshot,
        capability_reader=lambda config: SimpleNamespace(as_dict=lambda: {"available": True, "count": 0, "commands": [], "battery_tests": [], "beeper_control": False, "load_control": False, "shutdown_control": False, "supported_features": []}),
        shutdown_policy_reader=lambda: policy,
        shutdown_history_tracker=tracker,
    )

    assert runtime.startup() is True
    assert tracker.observed == ["OB FSD"]
    state = bridge.states[-1]
    assert state["shutdown_policy"]["guest_shutdown_budget_seconds"] == 420
    assert state["shutdown_readiness"]["status"] == "warning"
    assert "vm:110:timeout" in state["shutdown_readiness"]["issues"]
