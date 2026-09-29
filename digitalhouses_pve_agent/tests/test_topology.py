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
        if argv[:4] == ("udevadm", "info", "--query=property", "--path"):
            path = argv[4]
            if path.endswith("/1-3"):
                return """ID_VENDOR_FROM_DATABASE=QinHeng Electronics
ID_MODEL_FROM_DATABASE=CH340 serial converter
"""
            if path.endswith("/1-4"):
                return """ID_VENDOR_FROM_DATABASE=Cyber Power System, Inc.
ID_MODEL_FROM_DATABASE=PR1500LCDRT2U UPS
"""
            if path.endswith("/1-10"):
                return """ID_VENDOR_FROM_DATABASE=Intel Corp.
ID_MODEL_FROM_DATABASE=AX201 Bluetooth
"""
            return ""
        if argv[:3] == ("qm", "guest", "exec") and argv[3] == "700":
            return (FIX / "qga_lsblk_vm700.json").read_text()
        raise AssertionError(f"unexpected command: {argv}")


def config_reader(kind: str, guest_id: str) -> str:
    if kind == "vm" and guest_id == "700":
        return (FIX / "vm_700.conf").read_text()
    if kind == "vm" and guest_id == "501":
        return (FIX / "vm_501.conf").read_text()
    if kind == "vm" and guest_id in {"110", "99100"}:
        return "agent: 1\nname: haos\nusb0: host=1a86:7523\n"
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
                    "99100": {"node": "pve", "type": "qemu", "version": 4},
                    "500": {"node": "pve", "type": "lxc", "version": 5},
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
                "pve2.3-vm/99100:0:ha-prod:stopped:0:100:4:U:4294967296:U:34359738368:8589934592:U:U:U:U",
                "pve2.3-vm/500:600:recorder:running:0:100:2:0.1:2147483648:1073741824:34359738368:8589934592:1:2:3:4",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_usb_device(
    root: Path,
    name: str,
    *,
    vendor: str,
    product_id: str,
    manufacturer: str | None = None,
    product: str | None = None,
    serial: str | None = None,
    busnum: int = 1,
    devnum: int = 1,
) -> None:
    device = root / name
    device.mkdir(parents=True, exist_ok=True)
    (device / "idVendor").write_text(vendor + "\n")
    (device / "idProduct").write_text(product_id + "\n")
    (device / "busnum").write_text(str(busnum) + "\n")
    (device / "devnum").write_text(str(devnum) + "\n")
    if manufacturer is not None:
        (device / "manufacturer").write_text(manufacturer + "\n")
    if product is not None:
        (device / "product").write_text(product + "\n")
    if serial is not None:
        (device / "serial").write_text(serial + "\n")


def _write_usb_inventory(root: Path) -> Path:
    usb_root = root / "usb"
    _write_usb_device(
        usb_root,
        "1-3",
        vendor="1a86",
        product_id="7523",
        product="USB Serial",
        devnum=2,
    )
    _write_usb_device(
        usb_root,
        "1-4",
        vendor="0764",
        product_id="0601",
        manufacturer="CPS",
        product="PR3000ELCDSL",
        serial="PTJGW2000085",
        devnum=3,
    )
    _write_usb_device(
        usb_root,
        "1-10",
        vendor="8087",
        product_id="0026",
        devnum=4,
    )
    return usb_root


def _manager(tmp_path: Path, runner: FakeRunner) -> TopologyManager:
    return TopologyManager(
        runner=runner,
        dri_to_pci={},
        config_reader=config_reader,
        pve_root=tmp_path,
        usb_sys_root=tmp_path / "usb",
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



def test_running_vm_recovers_qga_and_passthrough_storage_without_vm_restart(tmp_path: Path):
    _write_pve_cache(tmp_path, vm700_status="running")

    class RecoveryRunner(FakeRunner):
        def __init__(self):
            super().__init__()
            self.vm700_qga_available = False

        def __call__(self, argv, *, timeout=20.0, check=True):
            argv = tuple(argv)
            if argv == ("qm", "agent", "700", "ping"):
                self.calls.append(argv)
                if not self.vm700_qga_available:
                    raise RuntimeError("guest-ping timeout")
                return ""
            return super().__call__(argv, timeout=timeout, check=check)

    now = [0.0]
    recoveries = []
    runner = RecoveryRunner()
    manager = TopologyManager(
        runner=runner,
        dri_to_pci={},
        config_reader=config_reader,
        pve_root=tmp_path,
        usb_sys_root=tmp_path / "usb",
        node_name="pve",
        now_epoch=lambda: 110.0,
        now_monotonic=lambda: now[0],
        on_storage_recovered=lambda: recoveries.append("smart"),
    )

    snapshot = manager.full_scan()
    assert snapshot.vms["700"].status == "running"
    assert snapshot.qga["700"] == "unavailable"
    assert manager.vm_storage_sources() == ()

    runner.calls.clear()
    runner.vm700_qga_available = True

    # Guest polling is already rate-limited by the 60-second scheduler.
    # Recovery must not inherit a second 60-second QGA throttle from the
    # startup probe phase. Reproduce startup probe at t=5 and poll at t=60.
    manager._qga_last_probe["700"] = 5.0
    now[0] = 60.0

    status = manager.poll_guest_status()

    assert status.vms["700"].status == "running"
    assert manager.qga_state("700") == "available"
    sources = manager.vm_storage_sources()
    assert len(sources) == 1
    assert sources[0].device_path == "/dev/sdb"
    assert sources[0].serial == "S2PWNX0H603177N"
    assert recoveries == ["smart"]
    assert ("qm", "agent", "700", "ping") in runner.calls
    assert any(
        call[:4] == ("qm", "guest", "exec", "700")
        for call in runner.calls
    )


def test_qga_recovery_retries_storage_rescan_after_transient_guest_exec_failure(tmp_path: Path):
    _write_pve_cache(tmp_path, vm700_status="running")

    class RetryRunner(FakeRunner):
        def __init__(self):
            super().__init__()
            self.qga_available = False
            self.fail_next_storage_exec = True

        def __call__(self, argv, *, timeout=20.0, check=True):
            argv = tuple(argv)
            if argv == ("qm", "agent", "700", "ping"):
                self.calls.append(argv)
                if not self.qga_available:
                    raise RuntimeError("guest-ping timeout")
                return ""
            if (
                argv[:4] == ("qm", "guest", "exec", "700")
                and self.qga_available
                and self.fail_next_storage_exec
            ):
                self.calls.append(argv)
                self.fail_next_storage_exec = False
                raise RuntimeError("guest-exec transient failure")
            return super().__call__(argv, timeout=timeout, check=check)

    now = [0.0]
    recoveries = []
    runner = RetryRunner()
    manager = TopologyManager(
        runner=runner,
        dri_to_pci={},
        config_reader=config_reader,
        pve_root=tmp_path,
        usb_sys_root=tmp_path / "usb",
        node_name="pve",
        now_epoch=lambda: 110.0,
        now_monotonic=lambda: now[0],
        on_storage_recovered=lambda: recoveries.append("smart"),
    )

    snapshot = manager.full_scan()
    assert snapshot.qga["700"] == "unavailable"
    assert manager.vm_storage_sources() == ()

    runner.calls.clear()
    runner.qga_available = True
    now[0] = 60.0

    first = manager.poll_guest_status()

    assert first.vms["700"].status == "running"
    assert manager.qga_state("700") == "available"
    assert manager.vm_storage_sources() == ()
    assert recoveries == []
    assert ("qm", "agent", "700", "ping") in runner.calls
    assert any(call[:4] == ("qm", "guest", "exec", "700") for call in runner.calls)

    runner.calls.clear()
    now[0] = 120.0

    second = manager.poll_guest_status()

    assert second.vms["700"].status == "running"
    assert manager.qga_state("700") == "available"
    sources = manager.vm_storage_sources()
    assert len(sources) == 1
    assert sources[0].serial == "S2PWNX0H603177N"
    assert recoveries == ["smart"]
    assert ("qm", "agent", "700", "ping") not in runner.calls
    assert any(call[:4] == ("qm", "guest", "exec", "700") for call in runner.calls)


def test_usb_topology_keeps_duplicate_vm_assignments_and_host_devices(tmp_path: Path):
    _write_pve_cache(tmp_path, vm700_status="running")
    _write_usb_inventory(tmp_path)
    runner = FakeRunner()
    manager = _manager(tmp_path, runner)

    snapshot = manager.full_scan()

    assert sorted(snapshot.usb) == ["usb_vm_110_usb0", "usb_vm_99100_usb0"]
    assert snapshot.usb["usb_vm_110_usb0"].device is not None
    assert snapshot.usb["usb_vm_110_usb0"].device.usb_id == "1a86:7523"
    assert snapshot.usb["usb_vm_110_usb0"].device.display_name == (
        "QinHeng Electronics CH340 serial converter"
    )
    assert snapshot.usb["usb_vm_99100_usb0"].device is not None

    assert sorted(device.usb_id for device in snapshot.host_usb.values()) == [
        "0764:0601",
        "8087:0026",
    ]
    assert {
        device.usb_id: device.display_name
        for device in snapshot.host_usb.values()
    } == {
        "0764:0601": "Cyber Power System, Inc. PR3000ELCDSL",
        "8087:0026": "Intel Corp. AX201 Bluetooth",
    }

    guests = manager.guest_payload()
    assert guests["vms"]["110"]["passthrough_count"] == 1
    assert guests["vms"]["99100"]["passthrough_count"] == 1
