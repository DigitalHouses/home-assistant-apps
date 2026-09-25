from pathlib import Path

from app.collectors.guests import (
    is_physical_guest_disk,
    parse_cluster_resources,
    parse_hostpci,
    parse_lspci_catalog,
    parse_pct_list,
    parse_qga_lsblk,
    parse_qm_list,
)

FIX = Path(__file__).parent / "fixtures" / "guests"

LSPCI_TEXT = """0000:00:02.0 VGA compatible controller [0300]: Intel Corporation Alder Lake-N [UHD Graphics] [8086:46d1]\n0000:00:17.0 SATA controller [0106]: Intel Corporation Device [8086:54d3]\n"""


def test_parse_qm_and_pct_lists_normalizes_status_and_names():
    vms = parse_qm_list((FIX / "qm_list.txt").read_text())
    lxcs = parse_pct_list((FIX / "pct_list.txt").read_text())
    assert vms["700"].name == "TrueNAS"
    assert vms["700"].status == "running"
    assert vms["110"].status == "stopped"
    assert lxcs["500"].kind == "lxc"


def test_parse_cluster_resources_returns_vm_and_lxc_in_one_pass():
    text = """[
      {"type":"qemu","vmid":501,"name":"plex-vm","status":"running"},
      {"type":"qemu","vmid":700,"name":"TrueNAS","status":"running"},
      {"type":"qemu","vmid":777,"name":"digitalhouses.vip","status":"running","qmpstatus":"paused"},
      {"type":"lxc","vmid":101,"name":"postgresql","status":"running"},
      {"type":"lxc","vmid":150,"name":"nut-web","status":"stopped"}
    ]"""
    vms, lxcs = parse_cluster_resources(text)
    assert vms["501"].name == "plex-vm"
    assert vms["777"].status == "paused"
    assert lxcs["101"].status == "running"
    assert lxcs["150"].status == "stopped"


def test_parse_hostpci_resolves_storage_controller_and_gpu():
    catalog = parse_lspci_catalog(LSPCI_TEXT)
    storage = parse_hostpci((FIX / "vm_700.conf").read_text(), catalog)
    gpu = parse_hostpci((FIX / "vm_501.conf").read_text(), catalog)
    assert storage[0].pci_address == "0000:00:17.0"
    assert storage[0].pci_class.startswith("01")
    assert gpu[0].pci_class.startswith("03")


def test_qga_lsblk_excludes_qemu_system_disk_and_keeps_physical_ssd():
    items = parse_qga_lsblk((FIX / "qga_lsblk_vm700.json").read_text())
    physical = [item for item in items if is_physical_guest_disk(item)]
    assert [item.path for item in physical] == ["/dev/sdb"]
    assert physical[0].model == "Samsung SSD 850 EVO 1TB"
    assert physical[0].wwn == "0x5002538d41046527"
