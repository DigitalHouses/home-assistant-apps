from pathlib import Path

from app.topology import TopologyManager

FIX = Path(__file__).parent / "fixtures" / "guests"

LSPCI = """0000:00:02.0 VGA compatible controller [0300]: Intel Corporation Alder Lake-N [UHD Graphics] [8086:46d1]\n0000:00:17.0 SATA controller [0106]: Intel Corporation Device [8086:54d3]\n"""


class FakeRunner:
    def __init__(self):
        self.vm700_status = "running"
        self.config_reads = {"501": 0, "700": 0}

    def __call__(self, argv, *, timeout=20.0, check=True):
        argv = tuple(argv)
        if argv == ("qm", "list"):
            return (
                " VMID NAME STATUS MEM(MB) BOOTDISK(GB) PID\n"
                " 110 haos stopped 4096 32 0\n"
                " 501 plex-vm running 1024 32 1\n"
                f" 700 TrueNAS {self.vm700_status} 4096 32 2\n"
            )
        if argv == ("pct", "list"):
            return "VMID Status Lock Name\n500 running - recorder\n"
        if argv == ("lspci", "-Dnn"):
            return LSPCI
        if argv[:2] == ("qm", "config"):
            vmid = argv[2]
            if vmid in self.config_reads:
                self.config_reads[vmid] += 1
            if vmid == "700":
                return (FIX / "vm_700.conf").read_text()
            if vmid == "501":
                return (FIX / "vm_501.conf").read_text()
            return "agent: 1\nname: haos\n"
        if argv[:2] == ("pct", "config"):
            return "hostname: recorder\n"
        if argv[:2] == ("qm", "agent"):
            return ""
        if argv[:3] == ("qm", "guest", "exec") and argv[3] == "700":
            return (FIX / "qga_lsblk_vm700.json").read_text()
        raise AssertionError(f"unexpected command: {argv}")


def test_full_scan_builds_vm700_storage_and_vm501_gpu_ownership():
    runner = FakeRunner()
    manager = TopologyManager(runner=runner, dri_to_pci={})
    snapshot = manager.full_scan()
    assert snapshot.vms["700"].name == "TrueNAS"
    assert snapshot.pci["0000:00:17.0"].owner_id == "700"
    assert snapshot.pci["0000:00:17.0"].device.pci_class.startswith("01")
    assert snapshot.pci["0000:00:02.0"].owner_id == "501"
    sources = manager.vm_storage_sources()
    assert len(sources) == 1
    assert sources[0].guest_id == "700"
    assert sources[0].device_path == "/dev/sdb"


def test_unchanged_status_poll_does_not_reread_guest_configs():
    runner = FakeRunner()
    manager = TopologyManager(runner=runner, dri_to_pci={})
    manager.full_scan()
    before = dict(runner.config_reads)
    manager.poll_guest_status()
    assert runner.config_reads == before


def test_guest_status_transition_to_running_triggers_targeted_rescan():
    runner = FakeRunner()
    runner.vm700_status = "stopped"
    manager = TopologyManager(runner=runner, dri_to_pci={})
    manager.full_scan()
    before = runner.config_reads["700"]
    runner.vm700_status = "running"
    status = manager.poll_guest_status()
    assert status.vms["700"].status == "running"
    assert runner.config_reads["700"] == before + 1
    assert manager.vm_storage_sources()[0].device_path == "/dev/sdb"
