import json
from pathlib import Path

from app.collectors.guests import parse_cluster_resources


def test_cluster_resource_node_filter_is_case_insensitive():
    payload = json.dumps([
        {"type": "qemu", "vmid": 501, "name": "plex-vm", "status": "running", "node": "pve"},
        {"type": "qemu", "vmid": 700, "name": "TrueNAS", "status": "running", "node": "pve"},
        {"type": "lxc", "vmid": 101, "name": "postgresql", "status": "running", "node": "pve"},
    ])

    vms, lxcs = parse_cluster_resources(payload, node_name="PVE")

    assert set(vms) == {"501", "700"}
    assert set(lxcs) == {"101"}


def test_main_does_not_use_configured_display_node_name_for_topology_filtering():
    text = (Path(__file__).parents[1] / "app" / "main.py").read_text(encoding="utf-8")

    assert "TopologyManager(runner=_run)" in text
    assert "TopologyManager(runner=_run, node_name=identity.node_name)" not in text
