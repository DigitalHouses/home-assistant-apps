from pathlib import Path

from app.topology import TopologyManager

FIX = Path(__file__).parent / "fixtures" / "guests"

LSPCI = """0000:00:02.0 VGA compatible controller [0300]: Intel Corporation Alder Lake-N [UHD Graphics] [8086:46d1]\n0000:00:17.0 SATA controller [0106]: Intel Corporation Device [8086:54d3]\n"""


class FakeRunner:
    def __init__(self):
        self.vm700_status = "running"
        self.calls = []

    def __call__(self, argv, *, timeout=20.0, check=True):
        argv = tuple(argv)
        self.calls.append(argv)
        if argv == ("pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json"):
            return (
                '[{"type":"qemu","vmid":110,"name":"haos","status":"stopped"},'
                '{"type":"qemu","vmid":501,"name":"plex-vm","status":"running"},'
                f'{{"type":"qemu","vmid":700,"name":"TrueNAS","status":"{self.vm700_status}"}},'
                '{"type":"lxc","vmid":500,"name":"recorder","status":"running"}]'
            )
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


def test_full_scan_builds_vm700_storage_and_vm501_gpu_ownership_without_config_commands():
    runner = FakeRunner()
    manager = TopologyManager(runner=runner, dri_to_pci={}, config_reader=config_reader)
    snapshot = manager.full_scan()
    assert snapshot.vms["700"].name == "TrueNAS"
    assert snapshot.pci["0000:00:17.0"].owner_id == "700"
    assert snapshot.pci["0000:00:17.0"].device.pci_class.startswith("01")
    assert snapshot.pci["0000:00:02.0"].owner_id == "501"
    sources = manager.vm_storage_sources()
    assert len(sources) == 1
    assert sources[0].guest_id == "700"
    assert sources[0].device_path == "/dev/sdb"
    assert not any(call[:2] in {("qm", "config"), ("pct", "config")} for call in runner.calls)


def test_unchanged_status_poll_uses_one_cluster_resources_command_only():
    runner = FakeRunner()
    manager = TopologyManager(runner=runner, dri_to_pci={}, config_reader=config_reader)
    manager.full_scan()
    runner.calls.clear()
    manager.poll_guest_status()
    status_calls = [call for call in runner.calls if call and call[0] in {"pvesh", "qm", "pct"}]
    assert status_calls == [
        ("pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json")
    ]


def test_guest_status_transition_to_running_triggers_targeted_rescan_without_config_command():
    runner = FakeRunner()
    runner.vm700_status = "stopped"
    manager = TopologyManager(runner=runner, dri_to_pci={}, config_reader=config_reader)
    manager.full_scan()
    runner.calls.clear()
    runner.vm700_status = "running"
    status = manager.poll_guest_status()
    assert status.vms["700"].status == "running"
    assert manager.vm_storage_sources()[0].device_path == "/dev/sdb"
    assert not any(call[:2] in {("qm", "config"), ("pct", "config")} for call in runner.calls)
