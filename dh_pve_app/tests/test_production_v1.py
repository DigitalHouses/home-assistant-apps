import json
from pathlib import Path

from app.production_v1 import (
    ResilientProductionCollectors,
    boot_time_iso,
    parse_primary_ip,
)
from app.state_store import StateStore
from app.topology import GuestStorageSource

FIX = Path(__file__).parent / "fixtures" / "disks"
GUEST_FIX = Path(__file__).parent / "fixtures" / "guests"


def _collector(tmp_path, topology=None):
    return ResilientProductionCollectors(
        node_name="PVE",
        disk_state_store=StateStore(tmp_path / "disks.json"),
        topology=topology,
    )


def test_host_helpers_return_ready_to_publish_values():
    assert boot_time_iso(1788813522) == "2026-09-07T20:38:42+00:00"
    assert parse_primary_ip(
        '[{"dst":"1.1.1.1","gateway":"192.168.11.1","prefsrc":"192.168.11.30","dev":"vmbr0"}]'
    ) == "192.168.11.30"
    assert parse_primary_ip("not json") is None


def test_one_smart_read_failure_marks_only_that_disk_unavailable(tmp_path, monkeypatch):
    collector = _collector(tmp_path)
    raw = (FIX / "nvme_samsung_990_evo.json").read_text()
    monkeypatch.setattr(collector, "_smart_scan", lambda: (("/dev/nvme0", "-d", "nvme"),))
    monkeypatch.setattr(collector, "_smart_read", lambda entry: raw)

    first = collector.smart()
    disk_id = next(iter(first.data))
    assert first.data[disk_id]["available"] is True

    def fail(entry):
        raise TimeoutError("smartctl timeout")

    monkeypatch.setattr(collector, "_smart_read", fail)
    second = collector.smart()

    assert list(second.data) == [disk_id]
    assert second.data[disk_id]["available"] is False
    assert "smartctl timeout" in second.data[disk_id]["error"]
    assert second.metrics[f"{disk_id}.available"].value is False


def test_missing_disk_requires_three_authoritative_scans_before_removal(tmp_path, monkeypatch):
    collector = _collector(tmp_path)
    raw = (FIX / "nvme_samsung_990_evo.json").read_text()
    monkeypatch.setattr(collector, "_smart_scan", lambda: (("/dev/nvme0", "-d", "nvme"),))
    monkeypatch.setattr(collector, "_smart_read", lambda entry: raw)

    first = collector.smart()
    disk_id = next(iter(first.data))

    monkeypatch.setattr(collector, "_smart_scan", lambda: ())
    second = collector.smart()
    third = collector.smart()
    fourth = collector.smart()

    assert disk_id in second.data
    assert disk_id in third.data
    assert second.data[disk_id]["available"] is False
    assert third.data[disk_id]["available"] is False
    assert disk_id not in fourth.data


def test_resilient_smart_state_is_json_serializable(tmp_path, monkeypatch):
    collector = _collector(tmp_path)
    raw = (FIX / "nvme_samsung_990_evo.json").read_text()
    monkeypatch.setattr(collector, "_smart_scan", lambda: (("/dev/nvme0", "-d", "nvme"),))
    monkeypatch.setattr(collector, "_smart_read", lambda entry: raw)

    sample = collector.smart()
    json.dumps(sample.data)
    json.dumps({key: metric.value for key, metric in sample.metrics.items()})


class FakeTopology:
    def __init__(self):
        self.status = "running"
        self.source = GuestStorageSource(
            guest_id="700",
            guest_name="TrueNAS",
            guest_status="running",
            device_path="/dev/sdb",
            model="Samsung SSD 850 EVO 1TB",
            serial="S2PWNX0H603177N",
            wwn="0x5002538d41046527",
            size_bytes=1000204886016,
            transport="sata",
            passthrough_hostpci="hostpci0",
        )

    def vm_storage_sources(self):
        source = self.source
        if source.guest_status == self.status:
            return (source,)
        return (GuestStorageSource(**{**source.__dict__, "guest_status": self.status}),)

    def guest_status(self, guest_id):
        assert guest_id == "700"
        return self.status

    def qga_state(self, guest_id):
        return "available" if self.status == "running" else "unavailable"

    def guest_exec(self, guest_id, command, *, timeout=12.0):
        assert guest_id == "700"
        if self.status != "running":
            raise RuntimeError("guest is not running")
        assert "smartctl -a -j /dev/sdb" in command
        return (GUEST_FIX / "samsung_850_evo_smart.json").read_text()


def _find_serial(sample, serial):
    return next(value for value in sample.data.values() if value.get("serial") == serial)


def test_smart_merges_local_nvme_and_vm700_passthrough_ssd(tmp_path, monkeypatch):
    topology = FakeTopology()
    collector = _collector(tmp_path, topology=topology)
    local_raw = (FIX / "nvme_samsung_990_evo.json").read_text()
    monkeypatch.setattr(collector, "_smart_scan", lambda: (("/dev/nvme0", "-d", "nvme"),))
    monkeypatch.setattr(collector, "_smart_read", lambda entry: local_raw)

    sample = collector.smart()
    local = _find_serial(sample, "S7M3NL0Y413841D")
    guest = _find_serial(sample, "S2PWNX0H603177N")
    assert local["available"] is True
    assert guest["model"] == "Samsung SSD 850 EVO 1TB"
    assert guest["available"] is True
    assert guest["source_type"] == "guest"
    assert guest["source_guest_id"] == "700"
    assert guest["source_guest_name"] == "TrueNAS"
    assert guest["source_device_path"] == "/dev/sdb"
    assert guest["passthrough_hostpci"] == "hostpci0"


def test_stopped_vm_marks_guest_disk_unavailable_without_removing_local_disk(tmp_path, monkeypatch):
    topology = FakeTopology()
    collector = _collector(tmp_path, topology=topology)
    local_raw = (FIX / "nvme_samsung_990_evo.json").read_text()
    monkeypatch.setattr(collector, "_smart_scan", lambda: (("/dev/nvme0", "-d", "nvme"),))
    monkeypatch.setattr(collector, "_smart_read", lambda entry: local_raw)

    first = collector.smart()
    assert _find_serial(first, "S2PWNX0H603177N")["available"] is True

    topology.status = "stopped"
    second = collector.smart()
    assert _find_serial(second, "S2PWNX0H603177N")["available"] is False
    assert _find_serial(second, "S7M3NL0Y413841D")["available"] is True
