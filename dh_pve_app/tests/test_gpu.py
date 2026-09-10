from pathlib import Path

from app.collectors.gpu import (
    GpuOwner,
    GuestInfo,
    build_gpu_snapshots,
    parse_intel_gpu_top_json,
    parse_lspci_gpus,
    parse_lxc_gpu_owners,
    parse_qemu_guest_exec_transcoding,
    parse_vm_gpu_owners,
    read_dri_pci_map,
    read_gpu_temperature,
)
from app.production_v1 import ResilientProductionCollectors
from app.state_store import StateStore

FIX = Path(__file__).parent / "fixtures" / "gpu"


def test_parse_real_shahristan_intel_gpu():
    items = parse_lspci_gpus((FIX / "shahristan_lspci.txt").read_text())
    assert len(items) == 1
    gpu = items[0]
    assert gpu["pci_address"] == "0000:00:02.0"
    assert gpu["vendor_id"] == "0x8086"
    assert gpu["device_id"] == "0x46d1"
    assert gpu["kernel_driver"] == "vfio-pci"
    assert gpu["display_name"] == "Intel Alder Lake-N UHD Graphics"


def test_vm_passthrough_owner_matches_real_plex_vm():
    guests = {"501": GuestInfo("501", "plex-vm", "running")}
    owners = parse_vm_gpu_owners(
        {"501": "name: plex-vm\nhostpci0: 0000:00:02.0\n"}, guests
    )
    owner = owners["0000:00:02.0"]
    assert owner.connection == "passthrough_pci"
    assert owner.source_type == "vm"
    assert owner.source_id == "501"
    assert owner.source_name == "plex-vm"
    assert owner.source_status == "running"
    assert owner.config == "hostpci0: 0000:00:02.0"


def test_parse_real_legacy_nvidia_gpu_and_dedupe_lxc_dri_nodes():
    items = parse_lspci_gpus((FIX / "legacy_lspci.txt").read_text())
    assert len(items) == 1
    assert items[0]["display_name"] == "NVIDIA GK208B GeForce GT 730"
    assert items[0]["kernel_driver"] == "nouveau"

    guests = {"500": GuestInfo("500", "plex", "running")}
    config = (
        "lxc.mount.entry: /dev/dri/card0 dev/dri/card0 none bind,optional,create=file\n"
        "lxc.mount.entry: /dev/dri/renderD128 dev/dri/renderD128 none bind,optional,create=file\n"
        "# duplicate token: /dev/dri/card0\n"
    )
    owners = parse_lxc_gpu_owners(
        {"500": config},
        guests,
        {"card0": "0000:01:00.0", "renderD128": "0000:01:00.0"},
    )
    owner = owners["0000:01:00.0"]
    assert owner.connection == "shared_dri"
    assert owner.source_id == "500"
    assert owner.source_name == "plex"
    assert owner.dri_devices == ("card0", "renderD128")


def test_no_gpu_is_valid_empty_inventory():
    assert parse_lspci_gpus((FIX / "no_gpu_lspci.txt").read_text()) == ()


def test_intel_gpu_top_ignores_short_first_sample_and_uses_peak_video_busy():
    metrics = parse_intel_gpu_top_json((FIX / "intel_gpu_top.jsonstream").read_text())
    assert metrics["supported"] is True
    assert metrics["available"] is True
    assert metrics["transcoding_load_percent"] == 71.3
    assert metrics["video_busy_percent"] == 71.3
    assert metrics["render_busy_percent"] == 18.0
    assert metrics["video_enhance_busy_percent"] == 10.0
    assert metrics["rc6_percent"] == 25.6
    assert metrics["sample_count"] == 2


def test_gpu_temperature_uses_max_sensor_bound_to_same_pci_device(tmp_path: Path):
    pci = "0000:01:00.0"
    pci_dir = tmp_path / "sys" / "bus" / "pci" / "devices" / pci
    pci_dir.mkdir(parents=True)
    hwmon = tmp_path / "sys" / "class" / "hwmon" / "hwmon2"
    hwmon.mkdir(parents=True)
    (hwmon / "temp1_input").write_text("37000\n")
    (hwmon / "temp2_input").write_text("41000\n")
    (hwmon / "device").symlink_to(pci_dir, target_is_directory=True)
    assert read_gpu_temperature(pci, sys_root=tmp_path / "sys") == 41.0


def test_snapshot_marks_known_vm_passthrough_and_transcoding():
    lspci = (FIX / "shahristan_lspci.txt").read_text()
    vm_owners = parse_vm_gpu_owners(
        {"501": "hostpci0: 0000:00:02.0\n"},
        {"501": GuestInfo("501", "plex-vm", "running")},
    )
    tr = parse_intel_gpu_top_json((FIX / "intel_gpu_top.jsonstream").read_text())
    snaps = build_gpu_snapshots(
        lspci,
        vm_owners=vm_owners,
        transcoding={"0000:00:02.0": tr},
    )
    gpu = snaps[0]
    assert gpu.gpu_id == "pci_0000_00_02_0"
    assert gpu.owner == "VM 501"
    assert gpu.connection == "passthrough_pci"
    assert gpu.transcoding_supported is True
    assert gpu.transcoding_available is True
    assert gpu.transcoding_load_percent == 71.3
    assert gpu.transcoding_source == "intel_gpu_top"
    assert gpu.config == "hostpci0: 0000:00:02.0"


def test_unclaimed_vfio_gpu_is_reserved_unknown_owner():
    gpu = build_gpu_snapshots((FIX / "shahristan_lspci.txt").read_text())[0]
    assert gpu.owner == "VFIO"
    assert gpu.connection == "passthrough_or_reserved"
    assert gpu.source_type == "unknown"


def test_qemu_guest_exec_wrapper_adds_source_and_vm_id():
    raw = (FIX / "intel_gpu_top.jsonstream").read_text()
    import json

    outer = json.dumps({"exitcode": 0, "out-data": raw})
    metrics = parse_qemu_guest_exec_transcoding(outer, "501")
    assert metrics["transcoding_load_percent"] == 71.3
    assert metrics["source"] == "qemu_guest_agent_intel_gpu_top"
    assert metrics["vm_id"] == "501"


def test_dri_to_pci_mapping_uses_sysfs_device_symlink(tmp_path: Path):
    sys_root = tmp_path / "sys"
    pci = sys_root / "devices" / "pci0000:00" / "0000:00:02.0"
    pci.mkdir(parents=True)
    drm = sys_root / "class" / "drm"
    for node in ("card0", "renderD128"):
        item = drm / node
        item.mkdir(parents=True)
        (item / "device").symlink_to(pci, target_is_directory=True)
    assert read_dri_pci_map(sys_root) == {
        "card0": "0000:00:02.0",
        "renderD128": "0000:00:02.0",
    }


class CachedGpuTopology:
    def __init__(self):
        self.guest_exec_calls = 0

    def gpu_owners(self):
        return {
            "0000:00:02.0": GpuOwner(
                connection="passthrough_pci",
                source_type="vm",
                source_id="501",
                source_name="plex-vm",
                source_status="running",
                config="hostpci0: 0000:00:02.0",
            )
        }

    def guest_status(self, guest_id):
        assert guest_id == "501"
        return "running"

    def qga_state(self, guest_id):
        assert guest_id == "501"
        return "available"

    def guest_exec(self, guest_id, command, *, timeout=12.0):
        assert guest_id == "501"
        assert "intel_gpu_top" in command
        self.guest_exec_calls += 1
        return (FIX / "intel_gpu_top.jsonstream").read_text()


def test_gpu_uses_cached_topology_and_keeps_vm501_transcoding(tmp_path, monkeypatch):
    import app.production as production
    import app.production_v1 as production_v1

    topology = CachedGpuTopology()
    calls = []

    def fake_run(argv, *, timeout=20.0, check=True):
        calls.append(tuple(argv))
        if tuple(argv) == ("lspci", "-Dnnk"):
            return (FIX / "shahristan_lspci.txt").read_text()
        if argv and argv[0] in {"qm", "pct"}:
            return ""
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(production, "_run", fake_run)
    monkeypatch.setattr(production_v1, "_run", fake_run)

    collector = ResilientProductionCollectors(
        node_name="PVE",
        disk_state_store=StateStore(tmp_path / "disks.json"),
        topology=topology,
        sys_root=tmp_path / "sys",
        pve_root=tmp_path / "pve",
    )
    first = collector.gpu()
    second = collector.gpu()
    gpu = first.data["pci_0000_00_02_0"]
    assert gpu["owner"] == "VM 501"
    assert gpu["source_name"] == "plex-vm"
    assert gpu["transcoding_load_percent"] == 71.3
    assert topology.guest_exec_calls == 2
    assert not any(call and call[0] in {"qm", "pct"} for call in calls)
    assert second.data["pci_0000_00_02_0"]["owner"] == "VM 501"
