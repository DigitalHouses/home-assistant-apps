from __future__ import annotations

from pathlib import Path

import pytest

from app.pve_cache import (
    read_pve_rrd,
    read_pve_version,
    read_pve_vmlist,
    read_storage_config,
)


FIXTURES = Path(__file__).parent / "fixtures"


def test_pve_version_returns_stable_fingerprint_for_parsed_json():
    first = read_pve_version(FIXTURES / "pve8_version.json")
    second = read_pve_version(FIXTURES / "pve8_version.json")

    assert first.vmlist_version == 42
    assert first.fingerprint
    assert first.fingerprint == second.fingerprint


def test_pve_version_rejects_non_object_json(tmp_path: Path):
    path = tmp_path / ".version"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="object"):
        read_pve_version(path)


def test_pve_vmlist_maps_local_qemu_and_lxc_without_runtime_status():
    snap = read_pve_vmlist(FIXTURES / "pve8_vmlist.json", node_name="pve")

    assert snap.version == 42
    assert set(snap.guests) == {"110", "700", "1011"}
    assert snap.guests["110"].kind == "vm"
    assert snap.guests["700"].kind == "vm"
    assert snap.guests["1011"].kind == "lxc"
    assert snap.guests["110"].node == "pve"
    assert snap.guests["110"].version == 11


def test_pve_vmlist_ignores_unknown_guest_types(tmp_path: Path):
    path = tmp_path / ".vmlist"
    path.write_text(
        '{"version":1,"ids":{"100":{"node":"pve","type":"future","version":1}}}',
        encoding="utf-8",
    )

    snap = read_pve_vmlist(path, node_name="pve")

    assert snap.guests == {}


def test_pve_rrd_parses_guest_status_and_storage_usage_without_zeroing_unknowns():
    snap = read_pve_rrd(
        FIXTURES / "pve8_rrd.txt",
        node_name="pve",
        now_epoch=1720000110,
    )

    assert snap.node is not None
    assert snap.node.loadavg1 == pytest.approx(0.42)
    assert snap.node.uptime_seconds == pytest.approx(3600.0)
    assert snap.guests["110"].status == "running"
    assert snap.guests["110"].cpu == pytest.approx(0.02)
    assert snap.guests["700"].status == "stopped"
    assert snap.guests["700"].cpu is None
    assert snap.guests["700"].memory_used is None
    assert snap.storages["local-lvm"].used == pytest.approx(700000000.0)
    assert snap.storages["local-lvm"].usage_percent == pytest.approx(70.0)


def test_pve_rrd_rejects_stale_records_instead_of_zeroing_them():
    snap = read_pve_rrd(
        FIXTURES / "pve8_rrd.txt",
        node_name="pve",
        now_epoch=1720000300,
    )

    assert snap.node is None
    assert snap.guests == {}
    assert snap.storages == {}


def test_pve_rrd_ignores_unknown_future_keys():
    snap = read_pve_rrd(
        FIXTURES / "pve8_rrd.txt",
        node_name="pve",
        now_epoch=1720000110,
    )

    assert set(snap.guests) == {"110", "700"}
    assert set(snap.storages) == {"local-lvm"}


def test_storage_config_parses_storage_type_and_dependency_options():
    cfg = read_storage_config(FIXTURES / "pve8_storage.cfg")

    assert cfg["local"].storage_type == "dir"
    assert cfg["local-lvm"].storage_type == "lvmthin"
    assert cfg["truenas_data"].storage_type == "nfs"
    assert cfg["truenas_data"].options["server"] == "192.168.11.31"
    assert cfg["truenas_data"].options["export"] == "/mnt/sky_pool/data"


def test_storage_config_ignores_comments_and_blank_lines(tmp_path: Path):
    path = tmp_path / "storage.cfg"
    path.write_text(
        "# comment\n\ndir: local\n\tpath /var/lib/vz\n\n",
        encoding="utf-8",
    )

    cfg = read_storage_config(path)

    assert set(cfg) == {"local"}
    assert cfg["local"].options["path"] == "/var/lib/vz"


def test_pve_version_fingerprint_ignores_volatile_tasklist_but_tracks_config_revision(
    tmp_path: Path,
):
    path = tmp_path / ".version"
    base = {
        "starttime": 1789730467,
        "clinfo": 0,
        "vmlist": 1,
        "storage.cfg": 1,
        "kvstore": {
            "pve": {
                "kv/cpuflags-kvm": 0,
                "kv/cpuflags-tcg": 0,
                "kv/static-info": 0,
                "kv/version-info": 0,
                "tasklist": 653,
            }
        },
    }

    import json

    path.write_text(json.dumps(base), encoding="utf-8")
    first = read_pve_version(path)

    noisy = {
        **base,
        "kvstore": {
            "pve": {
                **base["kvstore"]["pve"],
                "tasklist": 654,
            }
        },
    }
    path.write_text(json.dumps(noisy), encoding="utf-8")
    second = read_pve_version(path)

    changed = {**noisy, "vmlist": 2}
    path.write_text(json.dumps(changed), encoding="utf-8")
    third = read_pve_version(path)

    assert first.fingerprint == second.fingerprint
    assert third.fingerprint != second.fingerprint
