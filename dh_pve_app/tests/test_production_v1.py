import json
from pathlib import Path

from app.production_v1 import (
    ResilientProductionCollectors,
    boot_time_iso,
    parse_primary_ip,
)
from app.state_store import StateStore

FIX = Path(__file__).parent / "fixtures" / "disks"


def _collector(tmp_path):
    return ResilientProductionCollectors(
        node_name="PVE",
        disk_state_store=StateStore(tmp_path / "disks.json"),
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
