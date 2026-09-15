from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class PveVersionSnapshot:
    raw: Mapping[str, object]
    vmlist_version: int | None
    fingerprint: str


@dataclass(frozen=True)
class PveGuestInventoryItem:
    vmid: str
    kind: str
    node: str
    version: int | None


@dataclass(frozen=True)
class PveGuestInventory:
    version: int | None
    guests: Mapping[str, PveGuestInventoryItem]


@dataclass(frozen=True)
class PveNodeRrd:
    node: str
    ctime: float
    uptime_seconds: float | None
    loadavg1: float | None
    maxcpu: float | None
    cpu: float | None
    iowait: float | None
    memory_total: float | None
    memory_used: float | None
    swap_total: float | None
    swap_used: float | None
    root_total: float | None
    root_used: float | None
    netin: float | None
    netout: float | None


@dataclass(frozen=True)
class PveGuestRrd:
    vmid: str
    ctime: float
    uptime_seconds: float | None
    name: str | None
    status: str | None
    template: bool | None
    cpus: float | None
    cpu: float | None
    memory_max: float | None
    memory_used: float | None
    disk_max: float | None
    disk_used: float | None
    netin: float | None
    netout: float | None
    diskread: float | None
    diskwrite: float | None


@dataclass(frozen=True)
class PveStorageRrd:
    node: str
    storage_id: str
    ctime: float
    total: float | None
    used: float | None
    free: float | None
    usage_percent: float | None


@dataclass(frozen=True)
class PveRrdSnapshot:
    node: PveNodeRrd | None
    guests: Mapping[str, PveGuestRrd]
    storages: Mapping[str, PveStorageRrd]


@dataclass(frozen=True)
class PveStorageConfig:
    storage_id: str
    storage_type: str
    options: Mapping[str, str]


def _read_json_object(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"PVE cache file must contain a JSON object: {path}")
    return raw


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def read_pve_version(path: Path) -> PveVersionSnapshot:
    raw = _read_json_object(path)
    canonical = json.dumps(
        raw,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return PveVersionSnapshot(
        raw=raw,
        vmlist_version=_optional_int(raw.get("vmlist")),
        fingerprint=hashlib.sha256(canonical).hexdigest(),
    )


def read_pve_vmlist(path: Path, *, node_name: str | None = None) -> PveGuestInventory:
    raw = _read_json_object(path)
    guests: dict[str, PveGuestInventoryItem] = {}
    ids = raw.get("ids")
    if ids is not None and not isinstance(ids, dict):
        raise ValueError("PVE .vmlist 'ids' must be an object")

    for raw_vmid, raw_item in (ids or {}).items():
        vmid = str(raw_vmid)
        if not vmid.isdigit() or not isinstance(raw_item, dict):
            continue
        node = raw_item.get("node")
        guest_type = raw_item.get("type")
        if not isinstance(node, str) or not node:
            continue
        if node_name is not None and node != node_name:
            continue
        if guest_type == "qemu":
            kind = "vm"
        elif guest_type == "lxc":
            kind = "lxc"
        else:
            continue
        guests[vmid] = PveGuestInventoryItem(
            vmid=vmid,
            kind=kind,
            node=node,
            version=_optional_int(raw_item.get("version")),
        )

    return PveGuestInventory(
        version=_optional_int(raw.get("version")),
        guests=guests,
    )


def _number(value: str) -> float | None:
    value = value.strip()
    if not value or value == "U":
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _ctime(fields: list[str], index: int) -> float | None:
    if index >= len(fields):
        return None
    value = _number(fields[index])
    if value is None or value < 0:
        return None
    return value


def _fresh(ctime: float | None, *, now_epoch: float, stale_after_seconds: float) -> bool:
    if ctime is None:
        return False
    return now_epoch - ctime <= stale_after_seconds


def _field(fields: list[str], index: int) -> str | None:
    if index >= len(fields):
        return None
    value = fields[index].strip()
    if not value or value == "U":
        return None
    return value


def _parse_node_rrd(
    node: str,
    fields: list[str],
    *,
    now_epoch: float,
    stale_after_seconds: float,
) -> PveNodeRrd | None:
    # PVE 8: uptime, subscription, ctime, loadavg1, maxcpu, cpu, iowait,
    # memtotal, memused, swaptotal, swapused, roottotal, rootused, netin, netout.
    if len(fields) < 15:
        return None
    ctime = _ctime(fields, 2)
    if not _fresh(ctime, now_epoch=now_epoch, stale_after_seconds=stale_after_seconds):
        return None
    assert ctime is not None
    return PveNodeRrd(
        node=node,
        ctime=ctime,
        uptime_seconds=_number(fields[0]),
        loadavg1=_number(fields[3]),
        maxcpu=_number(fields[4]),
        cpu=_number(fields[5]),
        iowait=_number(fields[6]),
        memory_total=_number(fields[7]),
        memory_used=_number(fields[8]),
        swap_total=_number(fields[9]),
        swap_used=_number(fields[10]),
        root_total=_number(fields[11]),
        root_used=_number(fields[12]),
        netin=_number(fields[13]),
        netout=_number(fields[14]),
    )


def _parse_guest_rrd(
    vmid: str,
    fields: list[str],
    *,
    now_epoch: float,
    stale_after_seconds: float,
) -> PveGuestRrd | None:
    # PVE 8: uptime, name, status, template, ctime, cpus, cpu, maxmem, mem,
    # maxdisk, disk, netin, netout, diskread, diskwrite.
    if len(fields) < 15:
        return None
    ctime = _ctime(fields, 4)
    if not _fresh(ctime, now_epoch=now_epoch, stale_after_seconds=stale_after_seconds):
        return None
    assert ctime is not None
    template_raw = _number(fields[3])
    template = None if template_raw is None else bool(int(template_raw))
    return PveGuestRrd(
        vmid=vmid,
        ctime=ctime,
        uptime_seconds=_number(fields[0]),
        name=_field(fields, 1),
        status=_field(fields, 2),
        template=template,
        cpus=_number(fields[5]),
        cpu=_number(fields[6]),
        memory_max=_number(fields[7]),
        memory_used=_number(fields[8]),
        disk_max=_number(fields[9]),
        disk_used=_number(fields[10]),
        netin=_number(fields[11]),
        netout=_number(fields[12]),
        diskread=_number(fields[13]),
        diskwrite=_number(fields[14]),
    )


def _parse_storage_rrd(
    node: str,
    storage_id: str,
    fields: list[str],
    *,
    now_epoch: float,
    stale_after_seconds: float,
) -> PveStorageRrd | None:
    if len(fields) < 3:
        return None
    ctime = _ctime(fields, 0)
    if not _fresh(ctime, now_epoch=now_epoch, stale_after_seconds=stale_after_seconds):
        return None
    assert ctime is not None
    total = _number(fields[1])
    used = _number(fields[2])
    free: float | None = None
    usage_percent: float | None = None
    if total is not None and used is not None and total > 0:
        free = max(0.0, total - used)
        usage_percent = used / total * 100.0
    return PveStorageRrd(
        node=node,
        storage_id=storage_id,
        ctime=ctime,
        total=total,
        used=used,
        free=free,
        usage_percent=usage_percent,
    )


def read_pve_rrd(
    path: Path,
    *,
    node_name: str,
    now_epoch: float,
    stale_after_seconds: float = 120.0,
) -> PveRrdSnapshot:
    if stale_after_seconds <= 0:
        raise ValueError("stale_after_seconds must be > 0")
    node: PveNodeRrd | None = None
    guests: dict[str, PveGuestRrd] = {}
    storages: dict[str, PveStorageRrd] = {}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, *fields = line.split(":")
        if key == f"pve2-node/{node_name}":
            parsed_node = _parse_node_rrd(
                node_name,
                fields,
                now_epoch=now_epoch,
                stale_after_seconds=stale_after_seconds,
            )
            if parsed_node is not None:
                node = parsed_node
            continue
        vm_prefix = "pve2.3-vm/"
        if key.startswith(vm_prefix):
            vmid = key[len(vm_prefix) :]
            if not vmid.isdigit():
                continue
            guest = _parse_guest_rrd(
                vmid,
                fields,
                now_epoch=now_epoch,
                stale_after_seconds=stale_after_seconds,
            )
            if guest is not None:
                guests[vmid] = guest
            continue
        storage_prefix = f"pve2-storage/{node_name}/"
        if key.startswith(storage_prefix):
            storage_id = key[len(storage_prefix) :]
            if not storage_id:
                continue
            storage = _parse_storage_rrd(
                node_name,
                storage_id,
                fields,
                now_epoch=now_epoch,
                stale_after_seconds=stale_after_seconds,
            )
            if storage is not None:
                storages[storage_id] = storage

    return PveRrdSnapshot(node=node, guests=guests, storages=storages)


def read_storage_config(path: Path) -> dict[str, PveStorageConfig]:
    result: dict[str, PveStorageConfig] = {}
    current_type: str | None = None
    current_id: str | None = None
    current_options: dict[str, str] = {}

    def flush() -> None:
        nonlocal current_type, current_id, current_options
        if current_type is not None and current_id is not None:
            result[current_id] = PveStorageConfig(
                storage_id=current_id,
                storage_type=current_type,
                options=dict(current_options),
            )
        current_type = None
        current_id = None
        current_options = {}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw_line[:1].isspace() and ":" in stripped:
            flush()
            storage_type, storage_id = stripped.split(":", 1)
            storage_type = storage_type.strip()
            storage_id = storage_id.strip()
            if storage_type and storage_id:
                current_type = storage_type
                current_id = storage_id
            continue
        if current_id is None:
            continue
        key, separator, value = stripped.partition(" ")
        if not separator:
            current_options[key] = ""
        else:
            current_options[key] = value.strip()

    flush()
    return result
