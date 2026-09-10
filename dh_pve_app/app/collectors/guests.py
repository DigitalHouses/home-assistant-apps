from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Mapping

PCI_BDF_RE = re.compile(r"(?P<pci>(?:[0-9a-fA-F]{4}:)?[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7])")
HOSTPCI_LINE_RE = re.compile(r"^(?P<key>hostpci\d+):\s*(?P<value>.+)$", re.MULTILINE)
LSPCI_RE = re.compile(
    r"^(?P<pci>[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7])\s+"
    r"(?P<label>.+?)\s+\[(?P<class>[0-9a-fA-F]{4})\]:\s+"
    r"(?P<model>.+?)\s+\[(?P<vendor>[0-9a-fA-F]{4}):(?P<device>[0-9a-fA-F]{4})\]"
)
VALID_STATUSES = {"running", "paused", "stopped"}


@dataclass(frozen=True)
class GuestRecord:
    kind: str
    guest_id: str
    name: str
    status: str


@dataclass(frozen=True)
class PassthroughDevice:
    config_key: str
    pci_address: str
    pci_class: str
    class_name: str
    model: str
    vendor_id: str | None = None
    device_id: str | None = None


@dataclass(frozen=True)
class GuestBlockDevice:
    name: str
    path: str
    device_type: str
    size_bytes: int | None
    model: str | None
    serial: str | None
    wwn: str | None
    transport: str | None
    rotational: bool | None


def normalize_pci(value: str) -> str:
    value = value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", value):
        return "0000:" + value
    if re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", value):
        return value
    raise ValueError(f"invalid PCI address: {value}")


def _normalize_status(value: str) -> str:
    value = value.strip().lower()
    return value if value in VALID_STATUSES else "unknown"


def parse_qm_list(text: str) -> dict[str, GuestRecord]:
    result: dict[str, GuestRecord] = {}
    for raw in text.splitlines():
        parts = raw.split()
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        guest_id = parts[0]
        name = parts[1] if len(parts) > 1 else f"VM {guest_id}"
        status = _normalize_status(parts[2] if len(parts) > 2 else "unknown")
        result[guest_id] = GuestRecord("vm", guest_id, name, status)
    return result


def parse_pct_list(text: str) -> dict[str, GuestRecord]:
    result: dict[str, GuestRecord] = {}
    for raw in text.splitlines():
        parts = raw.split()
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        guest_id = parts[0]
        status = _normalize_status(parts[1])
        # `pct list` columns are VMID Status Lock Name. Lock can be empty,
        # therefore the guest name is most reliably the final field.
        name = parts[-1] if len(parts) > 2 else f"LXC {guest_id}"
        result[guest_id] = GuestRecord("lxc", guest_id, name, status)
    return result


def parse_cluster_resources(
    text: str,
    *,
    node_name: str | None = None,
) -> tuple[dict[str, GuestRecord], dict[str, GuestRecord]]:
    """Parse one `/cluster/resources --type vm` response into VM and LXC maps."""
    payload = json.loads(text)
    if not isinstance(payload, list):
        raise ValueError("cluster resources JSON must be an array")

    vms: dict[str, GuestRecord] = {}
    lxcs: dict[str, GuestRecord] = {}
    for raw in payload:
        if not isinstance(raw, Mapping):
            continue
        raw_node = raw.get("node")
        if (
            node_name
            and isinstance(raw_node, str)
            and raw_node
            and raw_node.casefold() != node_name.casefold()
        ):
            continue
        raw_type = str(raw.get("type") or "").strip().lower()
        if raw_type not in {"qemu", "lxc"}:
            continue
        vmid = raw.get("vmid")
        if isinstance(vmid, bool) or not isinstance(vmid, (int, str)):
            continue
        guest_id = str(vmid).strip()
        if not guest_id.isdigit():
            continue
        kind = "vm" if raw_type == "qemu" else "lxc"
        default_name = f"VM {guest_id}" if kind == "vm" else f"LXC {guest_id}"
        name = str(raw.get("name") or default_name).strip() or default_name
        # Some Proxmox endpoints expose the QEMU run state separately. Prefer
        # it when present so a paused VM does not collapse into `running`.
        qmpstatus = raw.get("qmpstatus")
        status_value = qmpstatus if isinstance(qmpstatus, str) and qmpstatus else raw.get("status")
        status = _normalize_status(str(status_value or "unknown"))
        record = GuestRecord(kind, guest_id, name, status)
        if kind == "vm":
            vms[guest_id] = record
        else:
            lxcs[guest_id] = record
    return vms, lxcs


def parse_lspci_catalog(text: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for raw in text.splitlines():
        match = LSPCI_RE.match(raw.strip())
        if not match:
            continue
        pci = normalize_pci(match.group("pci"))
        result[pci] = {
            "pci_address": pci,
            "pci_class": match.group("class").lower(),
            "class_name": match.group("label").strip(),
            "model": match.group("model").strip(),
            "vendor_id": "0x" + match.group("vendor").lower(),
            "device_id": "0x" + match.group("device").lower(),
        }
    return result


def parse_hostpci(
    config: str,
    pci_catalog: Mapping[str, Mapping[str, str]],
) -> tuple[PassthroughDevice, ...]:
    result: list[PassthroughDevice] = []
    for match in HOSTPCI_LINE_RE.finditer(config):
        bdf = PCI_BDF_RE.search(match.group("value"))
        if not bdf:
            continue
        pci = normalize_pci(bdf.group("pci"))
        meta = pci_catalog.get(pci, {})
        result.append(
            PassthroughDevice(
                config_key=match.group("key"),
                pci_address=pci,
                pci_class=str(meta.get("pci_class") or "unknown"),
                class_name=str(meta.get("class_name") or "Unknown PCI device"),
                model=str(meta.get("model") or pci),
                vendor_id=str(meta.get("vendor_id")) if meta.get("vendor_id") else None,
                device_id=str(meta.get("device_id")) if meta.get("device_id") else None,
            )
        )
    return tuple(result)


def _unwrap_qga_json(text: str) -> object:
    outer = json.loads(text)
    if isinstance(outer, dict) and "out-data" in outer:
        exitcode = outer.get("exitcode")
        if exitcode not in (None, 0):
            raise ValueError(f"QEMU guest exec failed: exitcode={exitcode!r}")
        inner = outer.get("out-data")
        if not isinstance(inner, str) or not inner.strip():
            raise ValueError("QEMU guest exec returned no output")
        return json.loads(inner)
    return outer


def parse_qga_lsblk(text: str) -> tuple[GuestBlockDevice, ...]:
    payload = _unwrap_qga_json(text)
    if not isinstance(payload, dict):
        raise ValueError("lsblk JSON must be an object")
    raw_items = payload.get("blockdevices")
    if not isinstance(raw_items, list):
        raise ValueError("lsblk JSON has no blockdevices array")

    result: list[GuestBlockDevice] = []
    for raw in raw_items:
        if not isinstance(raw, Mapping):
            continue
        name = raw.get("name")
        path = raw.get("path")
        device_type = raw.get("type")
        if not isinstance(name, str) or not isinstance(path, str) or not isinstance(device_type, str):
            continue
        size = raw.get("size")
        size_bytes = int(size) if isinstance(size, (int, float)) and not isinstance(size, bool) else None
        rotational = raw.get("rota") if isinstance(raw.get("rota"), bool) else None
        result.append(
            GuestBlockDevice(
                name=name,
                path=path,
                device_type=device_type,
                size_bytes=size_bytes,
                model=str(raw["model"]).strip() if raw.get("model") else None,
                serial=str(raw["serial"]).strip() if raw.get("serial") else None,
                wwn=str(raw["wwn"]).strip() if raw.get("wwn") else None,
                transport=str(raw["tran"]).strip() if raw.get("tran") else None,
                rotational=rotational,
            )
        )
    return tuple(result)


def is_physical_guest_disk(device: GuestBlockDevice) -> bool:
    if device.device_type != "disk":
        return False
    model = (device.model or "").strip().upper()
    serial = (device.serial or "").strip().lower()
    if model.startswith("QEMU HARDDISK") or model.startswith("VIRTUAL DISK"):
        return False
    if serial.startswith("drive-"):
        return False
    # Do not require WWN/transport: some real disks do not expose them through
    # every guest kernel/driver combination.
    return bool(device.path.startswith("/dev/"))
