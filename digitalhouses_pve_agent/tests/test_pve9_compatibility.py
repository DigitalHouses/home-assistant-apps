"""PVE 8/9 schema regression. PVE 9 records are synthetic, not live evidence.

Real 9.2 lab acceptance requires sanitized /etc/pve snapshots and a reboot.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.collectors.host import parse_pve_manager_version
from app.pve_cache import read_pve_rrd, read_pve_version, read_pve_vmlist

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("text", "version"),
    [
        ("pve-manager: 8.4.6 (running kernel: 6.8.12-13-pve)", "8.4.6"),
        ("pve-manager: 9.2.0 (running kernel: 7.0.14-29-pve)", "9.2.0"),
    ],
)
def test_pve_version_parser_is_not_coupled_to_major(text, version):
    assert parse_pve_manager_version(text) == version


def test_new_pmxcfs_keys_do_not_change_config_fingerprint_until_config_changes(tmp_path: Path):
    original = json.loads((FIXTURES / "pve8_version.json").read_text())
    original["future-pve9-key"] = {"backend": "potential extension"}
    original["kvstore"] = {"pve": {"tasklist": 16}}
    version = tmp_path / ".version"
    version.write_text(json.dumps(original))
    first = read_pve_version(version)
    original["kvstore"] = {"pve": {"tasklist": 17}}
    version.write_text(json.dumps(original))
    second = read_pve_version(version)
    assert first.fingerprint == second.fingerprint
    original["storage.cfg"] += 1
    version.write_text(json.dumps(original))
    assert read_pve_version(version).fingerprint != first.fingerprint


def test_pve9_synthetic_additive_rrd_fields_preserve_pve8_core_metrics(tmp_path: Path):
    # This verifies additive-field tolerance, NOT the actual PVE 9 RRD column order.
    rows = (FIXTURES / "pve8_rrd.txt").read_text().splitlines()
    future = [row + (":EXTRA" if row.startswith("pve2") else "") for row in rows]
    target = tmp_path / ".rrd"
    target.write_text("\n".join(future) + "\n")
    pve8 = read_pve_rrd(FIXTURES / "pve8_rrd.txt", node_name="pve", now_epoch=1720000110)
    pve9_like = read_pve_rrd(target, node_name="pve", now_epoch=1720000110)
    assert pve9_like.node == pve8.node
    assert pve9_like.guests == pve8.guests
    assert pve9_like.storages == pve8.storages


def test_pve9_synthetic_guest_map_keeps_qemu_lxc_semantics(tmp_path: Path):
    vmlist = {
        "version": 99,
        "ids": {
            "2223": {"node": "pve-k15", "type": "qemu", "version": 6},
            "1234": {"node": "pve-k15", "type": "lxc", "version": 7},
            "9999": {"node": "other", "type": "qemu", "version": 1},
        },
    }
    target = tmp_path / ".vmlist"
    target.write_text(json.dumps(vmlist))
    snap = read_pve_vmlist(target, node_name="pve-k15")
    assert set(snap.guests) == {"2223", "1234"}
    assert snap.guests["2223"].kind == "vm"
    assert snap.guests["1234"].kind == "lxc"
