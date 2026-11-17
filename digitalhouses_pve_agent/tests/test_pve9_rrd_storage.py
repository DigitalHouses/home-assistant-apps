from __future__ import annotations

from pathlib import Path

from app.pve_cache import read_pve_rrd
from app.production import ProductionCollectors
from app.state_store import StateStore

# PVE 9 keys and additive columns are based on the Proxmox pve-cluster RRD
# migration contract. Synthetic values; verify with live K15 after deploy.
NOW = 1720000110
PVE8_NODE = "pve2-node/pve:3600::1720000100:0.42:4:0.15:0.01:16000000000:4000000000:2000000000:100000000:32000000000:12000000000:1000:2000"
PVE9_NODE = "pve-node-9.0/pve:3600::1720000100:0.42:4:0.15:0.01:16000000000:4000000000:2000000000:100000000:32000000000:12000000000:1000:2000:0:0:0:0:0:0:0"
PVE8_GUEST = "pve2.3-vm/110:900:haos:running:0:1720000100:4:0.02:4294967296:2147483648:34359738368:8589934592:100:200:300:400"
PVE9_GUEST = "pve-vm-9.0/110:900:haos:running:0:1720000100:4:0.02:4294967296:2147483648:34359738368:8589934592:100:200:300:400:0:0:0:0:0:0:0"
PVE8_STORAGE = "pve2-storage/pve/local:1720000100:1000000000:700000000"
PVE9_STORAGE = "pve-storage-9.0/pve/local:1720000100:1000000000:400000000"


def rrd(tmp_path: Path, *rows: str):
    path = tmp_path / ".rrd"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return read_pve_rrd(path, node_name="pve", now_epoch=NOW)


def test_pve9_node_vm_storage_are_read_from_new_keys(tmp_path: Path):
    data = rrd(tmp_path, PVE9_NODE, PVE9_GUEST, PVE9_STORAGE)
    assert data.node is not None and data.node.loadavg1 == 0.42
    assert data.node.cpu == 0.15
    assert data.guests["110"].status == "running"
    assert data.guests["110"].memory_used == 2147483648
    assert data.storages["local"].used == 400000000
    assert data.storages["local"].usage_percent == 40.0


def test_mixed_pve8_pve9_prefers_new_keys_regardless_of_file_order(tmp_path: Path):
    for rows in (
        (PVE8_NODE, PVE9_NODE, PVE8_GUEST, PVE9_GUEST, PVE8_STORAGE, PVE9_STORAGE),
        (PVE9_STORAGE, PVE8_STORAGE, PVE9_GUEST, PVE8_GUEST, PVE9_NODE, PVE8_NODE),
    ):
        result = rrd(tmp_path, *rows)
        assert result.node is not None
        assert result.storages["local"].used == 400000000
        assert result.guests["110"].status == "running"


def test_pve9_stale_data_does_not_hide_fresh_pve8_data(tmp_path: Path):
    stale = PVE9_STORAGE.replace("1720000100", "1719999000")
    result = rrd(tmp_path, stale, PVE8_STORAGE)
    assert result.storages["local"].used == 700000000


def test_unknown_future_schema_not_guessed(tmp_path: Path):
    result = rrd(tmp_path, "pve-storage-10.0/pve/local:1720000100:100:60")
    assert result.storages == {}


def test_pve9_storage_collectors_expose_active_size_and_percent(tmp_path: Path):
    pve = tmp_path / "pve"
    pve.mkdir()
    (pve / "storage.cfg").write_text("dir: local\n\tpath /var/lib/vz\n")
    (pve / ".rrd").write_text(PVE9_STORAGE + "\n")
    collector = ProductionCollectors(
        node_name="pve",
        disk_state_store=StateStore(tmp_path / "smart.json"),
        pve_root=pve,
        now_epoch=lambda: NOW,
    )
    sample = collector.storage()
    local = sample.data["local"]
    assert local["active"] is True
    assert local["status"] == "active"
    assert local["usage_percent"] == 40.0
    assert local["total_kib"] == 976562
    assert sample.metrics["local.usage_percent"].value == 40.0


def test_pve8_storage_regression_is_unchanged(tmp_path: Path):
    result = rrd(tmp_path, PVE8_NODE, PVE8_GUEST, PVE8_STORAGE)
    assert result.storages["local"].usage_percent == 70.0
