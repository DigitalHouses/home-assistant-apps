from __future__ import annotations

import json
from pathlib import Path

from app.topology import TopologyManager

FIX = Path(__file__).parent / "fixtures" / "guests"

LSPCI = """0000:00:02.0 VGA compatible controller [0300]: Intel Corporation Alder Lake-N [UHD Graphics] [8086:46d1]\n0000:00:17.0 SATA controller [0106]: Intel Corporation Device [8086:54d3]\n"""


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, *, timeout=20.0, check=True):
        argv = tuple(argv)
        self.calls.append(argv)
        if argv == ("lspci", "-Dnn"):
            return LSPCI
        if argv[:2] == ("qm", "agent"):
            return ""
        if argv[:3] == ("qm", "guest", "exec") and argv[3] == "700":
            return (FIX / "qga_lsblk_vm700.json").read_text()
        raise AssertionError(f"unexpected command: {argv}")


def config_reader(kind: str, guest_id: str) -> str:
    if kind == "vm" and guest_id == "700":
        return (FIX / "vm_700.conf").read_text()
    if kind == "vm" and guest_id == "501":
        return (FIX / "vm_501.conf").read_text()
    if kind == "vm":
        return "agent: 1\nname: haos\n"
    return "hostname: recorder\n"


def _write_pve_cache(root: Path, *, vm700_status: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".vmlist").write_text(
        json.dumps(
            {
                "version": 9,
                "ids": {
                    "110": {"node": "pve", "type": "qemu", "version": 1},
                    "501": {"node": "pve", "type": "qemu", "version": 2},
                    "700": {"node": "pve", "type": "qemu", "version": 3},
                    "500": {"node": "pve", "type": "lxc", "version": 4},
                },
            }
        ),
        encoding="utf-8",
    )
    (root / ".rrd").write_text(
        "\n".join(
            [
                "pve2.3-vm/110:0:haos:stopped:0:100:4:U:4294967296:U:34359738368:8589934592:U:U:U:U",
                "pve2.3-vm/501:600:plex-vm:running:0:100:2:0.1:2147483648:1073741824:34359738368:8589934592:1:2:3:4",
                f"pve2.3-vm/700:{'600' if vm700_status == 'running' else '0'}:TrueNAS:{vm700_status}:0:100:4:{'0.1' if vm700_status == 'running' else 'U'}:4294967296:{'2147483648' if vm700_status == 'running' else 'U'}:34359738368:8589934592:1:2:3:4",
                "pve2.3-vm/500:600:recorder:running:0:100:2:0.1:2147483648:1073741824:34359738368:8589934592:1:2:3:4",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _manager(tmp_path: Path, runner: FakeRunner) -> TopologyManager:
    return TopologyManager(
        runner=runner,
        dri_to_pci={},
        config_reader=config_reader,
        pve_root=tmp_path,
        node_name="pve",
        now_epoch=lambda: 110.0,
    )


def test_full_scan_builds_vm700_storage_and_vm501_gpu_ownership_without_guest_list_commands(tmp_path: Path):
    _write_pve_cache(tmp_path, vm700_status="running")
    runner = FakeRunner()
    manager = _manager(tmp_path, runner)

    snapshot = manager.full_scan()

    assert snapshot.vms["700"].name == "TrueNAS"
    assert snapshot.pci["0000:00:17.0"].owner_id == "700"
    assert snapshot.pci["0000:00:17.0"].device.pci_class.startswith("01")
    assert snapshot.pci["0000:00:02.0"].owner_id == "501"
    sources = manager.vm_storage_sources()
    assert len(sources) == 1
    assert sources[0].guest_id == "700"
    assert sources[0].device_path == "/dev/sdb"
    assert not any(call and call[0] in {"pvesh", "pct"} for call in runner.calls)
    assert not any(call[:2] in {("qm", "list"), ("qm", "config"), ("pct", "config")} for call in runner.calls)


def test_unchanged_status_poll_uses_only_pve_cache_and_no_guest_list_subprocesses(tmp_path: Path):
    _write_pve_cache(tmp_path, vm700_status="running")
    runner = FakeRunner()
    manager = _manager(tmp_path, runner)
    manager.full_scan()
    runner.calls.clear()

    status = manager.poll_guest_status()

    assert status.vms["700"].status == "running"
    assert runner.calls == []


def test_guest_status_transition_to_running_uses_rrd_then_targeted_rescan(tmp_path: Path):
    _write_pve_cache(tmp_path, vm700_status="stopped")
    runner = FakeRunner()
    manager = _manager(tmp_path, runner)
    manager.full_scan()
    runner.calls.clear()

    _write_pve_cache(tmp_path, vm700_status="running")
    status = manager.poll_guest_status()

    assert status.vms["700"].status == "running"
    assert ("vm", "700", "stopped", "running") in status.changed
    assert manager.vm_storage_sources()[0].device_path == "/dev/sdb"
    assert not any(call and call[0] in {"pvesh", "pct"} for call in runner.calls)
    assert not any(call[:2] in {("qm", "list"), ("qm", "config"), ("pct", "config")} for call in runner.calls)
