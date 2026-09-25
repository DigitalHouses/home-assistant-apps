from __future__ import annotations

from pathlib import Path

import app.production as production
from app.production import ProductionCollectors
from app.state_store import StateStore


def _write_storage_cache(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "storage.cfg").write_text(
        """dir: local
\tpath /var/lib/vz
\tcontent iso,vztmpl,backup

lvmthin: local-lvm
\tthinpool data
\tvgname pve
\tcontent images,rootdir

nfs: truenas_data
\tserver 192.168.11.31
\texport /mnt/sky_pool/data
\tcontent images,iso,vztmpl,backup,snippets
""",
        encoding="utf-8",
    )
    (root / ".rrd").write_text(
        "\n".join(
            [
                "pve2-storage/pve/local:100:1000000000:250000000",
                "pve2-storage/pve/local-lvm:100:2000000000:1400000000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_storage_reads_pmxcfs_cache_without_pvesm(tmp_path: Path, monkeypatch):
    pve_root = tmp_path / "pve"
    _write_storage_cache(pve_root)

    def forbidden_run(*args, **kwargs):
        raise AssertionError(f"unexpected subprocess: {args!r}")

    monkeypatch.setattr(production, "_run", forbidden_run)
    collector = ProductionCollectors(
        node_name="pve",
        disk_state_store=StateStore(tmp_path / "disks.json"),
        pve_root=pve_root,
        now_epoch=lambda: 110.0,
    )

    sample = collector.storage()

    assert sample.data["local"]["storage_type"] == "dir"
    assert sample.data["local"]["active"] is True
    assert sample.data["local"]["usage_percent"] == 25.0
    assert sample.data["local-lvm"]["usage_percent"] == 70.0
    assert sample.metrics["local-lvm.usage_percent"].value == 70.0


def test_configured_storage_without_fresh_rrd_is_unavailable_not_zero(tmp_path: Path, monkeypatch):
    pve_root = tmp_path / "pve"
    _write_storage_cache(pve_root)

    def forbidden_run(*args, **kwargs):
        raise AssertionError(f"unexpected subprocess: {args!r}")

    monkeypatch.setattr(production, "_run", forbidden_run)
    collector = ProductionCollectors(
        node_name="pve",
        disk_state_store=StateStore(tmp_path / "disks.json"),
        pve_root=pve_root,
        now_epoch=lambda: 300.0,
    )

    sample = collector.storage()

    assert sample.data["truenas_data"]["storage_type"] == "nfs"
    assert sample.data["truenas_data"]["active"] is False
    assert sample.data["truenas_data"]["usage_percent"] is None
    assert "truenas_data.usage_percent" not in sample.metrics
