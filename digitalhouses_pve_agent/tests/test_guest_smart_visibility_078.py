"""Guest SMART loss is telemetry failure, not disappearing physical storage."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.production_v1 import ResilientProductionCollectors
from app.state_store import StateStore
from app.topology import GuestStorageSource
from app.config import AppConfig, GeneralConfig, MqttConfig
from app.identity import HostIdentity
from app.shutdown_discovery import build_shutdown_aware_pve_discovery_payload


FIX = Path(__file__).parent / "fixtures" / "guests" / "samsung_850_evo_smart.json"


class GuestTopology:
    def __init__(self):
        self.qga = "available"
        self.status = "running"
        self.fail_inventory = False
        self.fail_smart = False
        self.source = GuestStorageSource(
            guest_id="2232", guest_name="mediaserver-serzhan",
            guest_status="running", device_path="/dev/sdb",
            model="Samsung SSD 850 EVO 1TB",
            serial="S2PWNX0H603177N", wwn="0x5002538d41046527",
            size_bytes=1000204886016, transport="sata",
            passthrough_hostpci="hostpci1",
        )

    def vm_storage_sources(self):
        if self.fail_inventory:
            raise TimeoutError("PCI guest inventory lookup timeout")
        return (self.source,)

    def guest_status(self, guest_id):
        assert guest_id == "2232"
        return self.status

    def qga_state(self, guest_id):
        assert guest_id == "2232"
        return self.qga

    def guest_exec(self, guest_id, command, *, timeout=12.0):
        assert guest_id == "2232"
        assert command == "smartctl -a -j /dev/sdb"
        if self.fail_smart:
            raise TimeoutError("QGA smartctl timeout")
        return FIX.read_text()


def _make_collector(tmp_path, topology):
    collector = ResilientProductionCollectors(
        node_name="PVE",
        disk_state_store=StateStore(tmp_path / "disks.json"),
        topology=topology,
    )
    collector._smart_scan = lambda: ()
    return collector


def _discovery(inventory):
    config = AppConfig(
        general=GeneralConfig(instance_id="", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(
            host="mqtt", port=1883, username="", password="",
            topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
            discovery_prefix="homeassistant", keepalive_seconds=60,
        ),
    )
    identity = HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a", hostname="pve", node_name="PVE",
    )
    return build_shutdown_aware_pve_discovery_payload(
        config, identity, version="0.5.78", inventory={"smart": inventory}
    )["components"]


def test_qga_timeout_keeps_same_disk_and_last_success_unavailable_without_stale_metrics(tmp_path):
    topology = GuestTopology()
    collector = _make_collector(tmp_path, topology)
    healthy = collector.smart()
    assert len(healthy.data) == 1
    disk_id = next(iter(healthy.data))
    first = healthy.data[disk_id]
    assert first["available"] is True
    assert first["last_success_at"].endswith("+00:00")
    assert first["health_state"] == "HEALTHY"

    topology.qga = "unavailable"
    for _ in range(4):
        stale = collector.smart()
        assert list(stale.data) == [disk_id]
        item = stale.data[disk_id]
        assert item["available"] is False
        assert "QEMU Guest Agent" in item["error"]
        assert item["last_success_at"] == first["last_success_at"]
        assert f"{disk_id}.health" not in stale.metrics
        assert stale.metrics[f"{disk_id}.available"].value is False

    persisted = collector.disk_state_store.load()
    assert disk_id in persisted["inventory"]
    assert persisted["missing_counts"][disk_id] == 0
    assert persisted["last_data"][disk_id]["available"] is True

    topology.qga = "available"
    recovered = collector.smart()
    assert list(recovered.data) == [disk_id]
    assert recovered.data[disk_id]["available"] is True
    assert recovered.data[disk_id]["error"] is None
    assert recovered.metrics[f"{disk_id}.available"].value is True


def test_failed_guest_smart_exec_keeps_identity_and_marks_data_unavailable(tmp_path):
    topology = GuestTopology()
    collector = _make_collector(tmp_path, topology)
    first = collector.smart()
    disk_id = next(iter(first.data))

    topology.fail_smart = True
    second = collector.smart()
    assert list(second.data) == [disk_id]
    assert second.data[disk_id]["available"] is False
    assert "QGA smartctl timeout" in second.data[disk_id]["error"]
    assert second.data[disk_id]["last_success_at"] == first.data[disk_id]["last_success_at"]


def test_transient_guest_inventory_failure_does_not_evict_disk_after_three_scans(tmp_path):
    topology = GuestTopology()
    collector = _make_collector(tmp_path, topology)
    original = collector.smart()
    disk_id = next(iter(original.data))

    topology.fail_inventory = True
    for _ in range(4):
        outage = collector.smart()
        assert list(outage.data) == [disk_id]
        assert outage.data[disk_id]["available"] is False
        assert "inventory temporarily unavailable" in outage.data[disk_id]["error"]

    assert disk_id in collector.disk_state_store.load()["inventory"]
    topology.fail_inventory = False
    assert collector.smart().data[disk_id]["available"] is True


def test_mqtt_health_identity_remains_online_but_current_smart_values_fail_closed():
    disk_id = "wwn_naa_5002538d41046527"
    comps = _discovery({disk_id: {
        "model": "Samsung SSD 850 EVO 1TB",
        "serial": "S2PWNX0H603177N",
        "disk_type": "SSD",
        "available": False,
        "health_state": "HEALTHY",
        "temperature_c": 35.0,
        "wear_used_percent": 25,
    }})
    health = comps[f"disk_{disk_id}_health"]
    temp = comps[f"disk_{disk_id}_temperature"]
    assert health["default_entity_id"] == f"sensor.dh_pve_agent_disk_{disk_id}_health"
    assert len(health["availability"]) == 2  # agent + SMART collector, NOT individual disk
    assert "TELEMETRY_UNAVAILABLE" in health["value_template"]
    assert ".available" in health["value_template"]
    for attr in ("telemetry_available", "telemetry_error", "last_success_at", "source_guest_id"):
        assert attr in health["json_attributes_template"]
    assert "last_known_health" in health["json_attributes_template"]
    assert ".available" in temp["availability"][-1]["value_template"]
    assert len(temp["availability"]) == 3
    # SMART problem binary sensors are independently published by the
    # Problems subsystem; disk-health status overrides the dashboard text
    # whenever telemetry is unavailable.


def test_dashboard_displays_telemetry_unavailable_without_healthy_smart_label():
    dashboard = (Path(__file__).parents[1] / "examples/dh_pve_agent_dashboard_ru.yaml").read_text()
    assert "states(health) == 'TELEMETRY_UNAVAILABLE'" in dashboard
    assert "SMART: телеметрия временно недоступна" in dashboard
