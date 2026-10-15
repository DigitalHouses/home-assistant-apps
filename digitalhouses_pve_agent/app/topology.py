from __future__ import annotations

import hashlib
import json
import logging
import platform
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping

from .collectors.gpu import GpuOwner, GuestInfo, parse_lxc_gpu_owners, read_dri_pci_map
from .collectors.guests import (
    GuestRecord,
    PassthroughDevice,
    UsbDevice,
    UsbPassthroughConfig,
    is_physical_guest_disk,
    parse_lspci_catalog,
    parse_qga_lsblk,
    parse_udev_properties,
    usb_display_name,
)
from .pci_native import parse_native_pci_inventory, parse_native_usb_inventory
from .pve_cache import read_pve_rrd, read_pve_vmlist

_LOG = logging.getLogger(__name__)
_NATIVE_PCI_SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "pve-pci-inventory"

Runner = Callable[..., str]
ConfigReader = Callable[[str, str], str]


@dataclass(frozen=True)
class PciAssignment:
    owner_kind: str
    owner_id: str
    owner_name: str
    device: PassthroughDevice


@dataclass(frozen=True)
class UsbAssignment:
    owner_kind: str
    owner_id: str
    owner_name: str
    config: UsbPassthroughConfig
    device: UsbDevice | None
    resolution: str = "missing"


@dataclass(frozen=True)
class GuestStorageSource:
    guest_id: str
    guest_name: str
    guest_status: str
    device_path: str
    model: str | None
    serial: str | None
    wwn: str | None
    size_bytes: int | None
    transport: str | None
    passthrough_hostpci: str


@dataclass(frozen=True)
class TopologySnapshot:
    vms: Mapping[str, GuestRecord]
    lxcs: Mapping[str, GuestRecord]
    pci: Mapping[str, PciAssignment]
    usb: Mapping[str, UsbAssignment]
    host_usb: Mapping[str, UsbDevice]
    gpu_owners: Mapping[str, GpuOwner]
    qga: Mapping[str, str]
    storage_sources: tuple[GuestStorageSource, ...]
    revision: str


@dataclass(frozen=True)
class GuestStatusSnapshot:
    vms: Mapping[str, GuestRecord]
    lxcs: Mapping[str, GuestRecord]
    changed: tuple[tuple[str, str, str, str], ...]


def _agent_enabled(config: str) -> bool:
    match = re.search(r"(?m)^agent:\s*(?P<value>.+?)\s*$", config)
    if not match:
        return False
    value = match.group("value").strip().lower()
    if value in {"0", "false", "no", "off"}:
        return False
    if value.startswith("enabled=0"):
        return False
    return value == "1" or value.startswith("enabled=1") or value in {"true", "yes", "on"}


def _guest_infos(records: Mapping[str, GuestRecord]) -> dict[str, GuestInfo]:
    return {
        guest_id: GuestInfo(guest_id, record.name, record.status)
        for guest_id, record in records.items()
    }


def _summary(records: Mapping[str, GuestRecord]) -> dict[str, int]:
    counts = {"total": len(records), "running": 0, "paused": 0, "stopped": 0, "unknown": 0}
    for item in records.values():
        key = item.status if item.status in counts else "unknown"
        counts[key] += 1
    return counts


class TopologyManager:
    """Process-local cache of guest state, passthrough topology and QGA sources."""

    def __init__(
        self,
        *,
        runner: Runner,
        dri_to_pci: Mapping[str, str] | None = None,
        now_monotonic: Callable[[], float] = time.monotonic,
        now_epoch: Callable[[], float] = time.time,
        config_reader: ConfigReader | None = None,
        pve_root: Path = Path("/etc/pve"),
        usb_sys_root: Path = Path("/sys/bus/usb/devices"),
        node_name: str | None = None,
    ) -> None:
        self.runner = runner
        self._fixed_dri_to_pci = dict(dri_to_pci) if dri_to_pci is not None else None
        self.now_monotonic = now_monotonic
        self.now_epoch = now_epoch
        self.config_reader = config_reader
        self.pve_root = pve_root
        self.usb_sys_root = usb_sys_root
        self.node_name = node_name or platform.node()
        self._snapshot: TopologySnapshot | None = None
        self._vm_configs: dict[str, str] = {}
        self._lxc_configs: dict[str, str] = {}
        self._pci_catalog: dict[str, dict[str, str]] = {}
        self._pci_assignments: dict[str, PciAssignment] = {}
        self._pci_inventory_errors: dict[str, str] = {}
        self._usb_inventory: dict[str, UsbDevice] = {}
        self._usb_configs: dict[str, tuple[UsbPassthroughConfig, ...]] = {}
        self._usb_inventory_errors: dict[str, str] = {}
        self._gpu_catalog_text = ""
        self._qga_last_probe: dict[str, float] = {}
        self._storage_sources: dict[tuple[str, str], GuestStorageSource] = {}

    @property
    def snapshot(self) -> TopologySnapshot | None:
        return self._snapshot

    def _run(self, argv: list[str], *, timeout: float = 20.0, check: bool = True) -> str:
        return self.runner(argv, timeout=timeout, check=check)

    def _guest_lists(self) -> tuple[dict[str, GuestRecord], dict[str, GuestRecord]]:
        """Read local VM/LXC inventory and current status from pmxcfs caches."""
        inventory = read_pve_vmlist(
            self.pve_root / ".vmlist",
            node_name=self.node_name,
        )
        runtime = read_pve_rrd(
            self.pve_root / ".rrd",
            node_name=self.node_name,
            now_epoch=self.now_epoch(),
        )
        vms: dict[str, GuestRecord] = {}
        lxcs: dict[str, GuestRecord] = {}
        for guest_id, item in inventory.guests.items():
            live = runtime.guests.get(guest_id)
            if live is not None and live.name:
                name = live.name
            elif item.kind == "vm":
                name = f"VM {guest_id}"
            else:
                name = f"LXC {guest_id}"
            status = live.status if live is not None and live.status else "unknown"
            record = GuestRecord(item.kind, guest_id, name, status)
            if item.kind == "vm":
                vms[guest_id] = record
            else:
                lxcs[guest_id] = record
        return vms, lxcs

    def _read_config(self, kind: str, guest_id: str) -> str:
        if self.config_reader is not None:
            return self.config_reader(kind, guest_id)

        directory = "qemu-server" if kind == "vm" else "lxc"
        path = self.pve_root / directory / f"{guest_id}.conf"
        return path.read_text(encoding="utf-8")

    def _qga_state(self, guest: GuestRecord, config: str, *, force: bool = False) -> str:
        if not _agent_enabled(config):
            return "disabled"
        if guest.status != "running":
            return "unavailable"
        now = self.now_monotonic()
        last = self._qga_last_probe.get(guest.guest_id)
        if not force and last is not None and now - last < 60.0 and self._snapshot is not None:
            previous = self._snapshot.qga.get(guest.guest_id)
            if previous in {"available", "unavailable"}:
                return previous
        self._qga_last_probe[guest.guest_id] = now
        try:
            self._run(["qm", "agent", guest.guest_id, "ping"], timeout=5)
        except Exception:
            return "unavailable"
        return "available"

    @staticmethod
    def _storage_passthrough(devices: tuple[PassthroughDevice, ...]) -> tuple[PassthroughDevice, ...]:
        return tuple(item for item in devices if item.pci_class.startswith("01"))

    def _probe_guest_storage(
        self,
        guest: GuestRecord,
        devices: tuple[PassthroughDevice, ...],
        qga_state: str,
    ) -> None:
        storage_devices = self._storage_passthrough(devices)
        if not storage_devices or guest.status != "running" or qga_state != "available":
            return
        command = "lsblk -J -b -d -o NAME,PATH,TYPE,SIZE,MODEL,SERIAL,WWN,TRAN,ROTA"
        try:
            raw = self._run(
                ["qm", "guest", "exec", guest.guest_id, "--", "/bin/sh", "-c", command],
                timeout=12,
            )
            block_devices = parse_qga_lsblk(raw)
        except Exception:
            return

        hostpci = ",".join(sorted({item.config_key for item in storage_devices}))
        seen: set[tuple[str, str]] = set()
        for block in block_devices:
            if not is_physical_guest_disk(block):
                continue
            key = (guest.guest_id, block.path)
            seen.add(key)
            self._storage_sources[key] = GuestStorageSource(
                guest_id=guest.guest_id,
                guest_name=guest.name,
                guest_status=guest.status,
                device_path=block.path,
                model=block.model,
                serial=block.serial,
                wwn=block.wwn,
                size_bytes=block.size_bytes,
                transport=block.transport,
                passthrough_hostpci=hostpci,
            )

        for key in list(self._storage_sources):
            if key[0] == guest.guest_id and key not in seen:
                self._storage_sources.pop(key, None)

    @staticmethod
    def _read_optional(path: Path) -> str | None:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return None
        return value or None

    def _scan_usb_inventory(self) -> dict[str, UsbDevice]:
        result: dict[str, UsbDevice] = {}
        try:
            entries = sorted(self.usb_sys_root.iterdir(), key=lambda item: item.name)
        except OSError:
            return result

        for entry in entries:
            vendor = self._read_optional(entry / "idVendor")
            product_id = self._read_optional(entry / "idProduct")
            if not vendor or not product_id:
                continue
            vendor = vendor.lower()
            product_id = product_id.lower()

            # Linux root hubs are infrastructure, not user-facing attached USB devices.
            if entry.name.startswith("usb") or (vendor == "1d6b" and product_id in {"0002", "0003"}):
                continue

            properties: dict[str, str] = {}
            try:
                raw = self._run(
                    ["udevadm", "info", "--query=property", "--path", str(entry)],
                    timeout=5,
                    check=False,
                )
                properties = parse_udev_properties(raw)
            except Exception:
                properties = {}

            usb_id = f"{vendor}:{product_id}"
            manufacturer = self._read_optional(entry / "manufacturer")
            product = self._read_optional(entry / "product")
            serial = self._read_optional(entry / "serial")
            database_vendor = properties.get("ID_VENDOR_FROM_DATABASE") or None
            database_model = properties.get("ID_MODEL_FROM_DATABASE") or None

            def _read_int(name: str) -> int | None:
                raw_value = self._read_optional(entry / name)
                if raw_value is None:
                    return None
                try:
                    return int(raw_value)
                except ValueError:
                    return None

            device = UsbDevice(
                sysfs_name=entry.name,
                usb_id=usb_id,
                vendor_id=vendor,
                product_id=product_id,
                manufacturer=manufacturer,
                product=product,
                serial=serial,
                busnum=_read_int("busnum"),
                devnum=_read_int("devnum"),
                physical_port=entry.name,
                database_vendor=database_vendor,
                database_model=database_model,
                display_name=usb_display_name(
                    manufacturer=manufacturer,
                    product=product,
                    database_vendor=database_vendor,
                    database_model=database_model,
                    usb_id=usb_id,
                ),
            )
            result[entry.name] = device
        return result

    def pci_inventory_errors(self) -> dict[str, str]:
        return dict(self._pci_inventory_errors)

    def usb_inventory_errors(self) -> dict[str, str]:
        return dict(self._usb_inventory_errors)

    def _refresh_native_pci(
        self,
        vms: Mapping[str, GuestRecord],
        guest_ids: tuple[str, ...] | None = None,
    ) -> None:
        """Read native PCI ownership only on topology scan or targeted guest rescan.

        A process/parse error preserves the last good topology; per-guest errors
        preserve only that VM's previous PCI assignments. No regex fallback.
        """
        requested = tuple(sorted(guest_ids if guest_ids is not None else vms))
        current = dict(self._pci_assignments)
        if not requested:
            if guest_ids is None:
                self._pci_assignments = {}
                self._pci_inventory_errors = {}
                self._usb_configs = {}
                self._usb_inventory_errors = {}
            return
        try:
            raw = self._run(
                ["perl", str(_NATIVE_PCI_SCRIPT), *requested],
                timeout=20.0,
            )
            native, errors = parse_native_pci_inventory(
                raw, set(requested), self._pci_catalog,
            )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self._pci_inventory_errors = {**self._pci_inventory_errors, "_global": message}
            self._usb_inventory_errors = {**self._usb_inventory_errors, "_global": message}
            _LOG.error("Native Proxmox passthrough inventory failed; retaining previous topology: %s", message)
            return

        result = {
            pci: value for pci, value in current.items()
            if value.owner_id not in requested and value.owner_id in vms
        }
        for pci, (guest_id, device) in native.items():
            if guest_id in errors:
                continue
            guest = vms[guest_id]
            result[pci] = PciAssignment(
                owner_kind="vm",
                owner_id=guest_id,
                owner_name=guest.name,
                device=device,
            )
        for pci, assignment in current.items():
            if assignment.owner_id in errors and assignment.owner_id in vms:
                result[pci] = assignment
        self._pci_assignments = result
        if guest_ids is None:
            self._pci_inventory_errors = errors
        else:
            self._pci_inventory_errors = {
                **{key: value for key, value in self._pci_inventory_errors.items()
                   if key not in requested and key != "_global"},
                **errors,
            }
        for vmid, error in errors.items():
            _LOG.error("Native PCI inventory VM %s: %s; preserving prior assignments", vmid, error)

        # The same native helper resolves USB selectors, including USB Resource
        # Mapping. Keep USB and PCI failure boundaries independent.
        try:
            usb_configs, usb_errors = parse_native_usb_inventory(raw, set(requested))
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self._usb_inventory_errors["_global"] = message
            _LOG.error("Native Proxmox USB inventory failed; preserving prior mappings: %s", message)
        else:
            latest = {
                vmid: configs for vmid, configs in self._usb_configs.items()
                if vmid not in requested and vmid in vms
            }
            for vmid in requested:
                if vmid in usb_errors:
                    if vmid in self._usb_configs:
                        latest[vmid] = self._usb_configs[vmid]
                else:
                    latest[vmid] = usb_configs.get(vmid, ())
            self._usb_configs = latest
            if guest_ids is None:
                self._usb_inventory_errors = usb_errors
            else:
                self._usb_inventory_errors = {
                    **{key: value for key, value in self._usb_inventory_errors.items()
                       if key not in requested and key != "_global"},
                    **usb_errors,
                }
            for vmid, error in usb_errors.items():
                _LOG.error("Native USB inventory VM %s: %s; retaining prior mappings", vmid, error)

    def _build_usb_assignments(
        self,
        vms: Mapping[str, GuestRecord],
    ) -> dict[str, UsbAssignment]:
        """Resolve unique physical USB devices; never pick first among duplicates.

        Process explicit port selectors first. VID:PID selectors can claim only
        the sole remaining matching device and only when a single VM requests it.
        A configured but ambiguous device has no asserted physical owner.
        """
        requests = [
            (vmid, item)
            for vmid, configs in sorted(self._usb_configs.items())
            if vmid in vms
            for item in configs
        ]
        physical = tuple(self._usb_inventory.values())
        assignments: dict[str, UsbAssignment] = {}
        resolved: dict[tuple[str, str], tuple[UsbDevice | None, str]] = {}
        reserved: set[str] = set()

        by_port: dict[str, list[tuple[str, str]]] = {}
        for vmid, item in requests:
            if item.physical_port:
                by_port.setdefault(item.physical_port, []).append((vmid, item.config_key))
        for port, keys in by_port.items():
            matches = [device for device in physical if device.physical_port == port]
            status = "resolved" if len(keys) == 1 and len(matches) == 1 else (
                "missing" if not matches else "ambiguous"
            )
            device = matches[0] if status == "resolved" else None
            if device is not None:
                reserved.add(device.sysfs_name)
            for key in keys:
                resolved[key] = (device, status)

        by_id: dict[str, list[tuple[str, str]]] = {}
        for vmid, item in requests:
            if item.usb_id:
                by_id.setdefault(item.usb_id, []).append((vmid, item.config_key))
        for usb_id, keys in by_id.items():
            matches = [
                device for device in physical
                if device.usb_id == usb_id and device.sysfs_name not in reserved
            ]
            status = "resolved" if len(keys) == 1 and len(matches) == 1 else (
                "missing" if not matches else "ambiguous"
            )
            device = matches[0] if status == "resolved" else None
            if device is not None:
                reserved.add(device.sysfs_name)
            for key in keys:
                resolved[key] = (device, status)

        for vmid, item in requests:
            device, status = resolved.get((vmid, item.config_key), (None, "missing"))
            key = f"usb_vm_{vmid}_{item.config_key}"
            assignments[key] = UsbAssignment(
                owner_kind="vm",
                owner_id=vmid,
                owner_name=vms[vmid].name,
                config=item,
                device=device,
                resolution=status,
            )
        return assignments

    def _host_usb_devices(
        self,
        assignments: Mapping[str, UsbAssignment],
    ) -> dict[str, UsbDevice]:
        # Hide only positively assigned physical devices. A duplicated VID:PID
        # does NOT hide all matching USB hardware from the host inventory.
        assigned = {
            item.device.sysfs_name for item in assignments.values()
            if item.device is not None
        }
        return {
            key: device for key, device in self._usb_inventory.items()
            if key not in assigned
        }

    def _build_gpu_owners(
        self,
        vms: Mapping[str, GuestRecord],
        lxcs: Mapping[str, GuestRecord],
        pci: Mapping[str, PciAssignment],
    ) -> dict[str, GpuOwner]:
        owners: dict[str, GpuOwner] = {}
        for address, assignment in pci.items():
            if not assignment.device.pci_class.startswith("03"):
                continue
            guest = vms.get(assignment.owner_id)
            owners[address] = GpuOwner(
                connection="passthrough_pci",
                source_type="vm",
                source_id=assignment.owner_id,
                source_name=assignment.owner_name,
                source_status=guest.status if guest is not None else "unknown",
                config=f"{assignment.device.config_key}: {assignment.device.pci_address}",
            )

        dri_map = (
            dict(self._fixed_dri_to_pci)
            if self._fixed_dri_to_pci is not None
            else read_dri_pci_map()
        )
        owners.update(
            parse_lxc_gpu_owners(self._lxc_configs, _guest_infos(lxcs), dri_map)
        )
        return owners

    def _revision(
        self,
        vms: Mapping[str, GuestRecord],
        lxcs: Mapping[str, GuestRecord],
        pci: Mapping[str, PciAssignment],
        usb: Mapping[str, UsbAssignment],
        host_usb: Mapping[str, UsbDevice],
    ) -> str:
        payload = {
            "vms": {key: self._vm_configs.get(key, "") for key in sorted(vms)},
            "lxcs": {key: self._lxc_configs.get(key, "") for key in sorted(lxcs)},
            "pci": {
                key: {
                    "owner": value.owner_id,
                    "kind": value.owner_kind,
                    "class": value.device.pci_class,
                    "key": value.device.config_key,
                }
                for key, value in sorted(pci.items())
            },
            "usb": {
                key: {
                    "owner": value.owner_id,
                    "kind": value.owner_kind,
                    "key": value.config.config_key,
                    "host": value.config.host,
                    "connected": value.device is not None,
                    "resolution": value.resolution,
                }
                for key, value in sorted(usb.items())
            },
            "host_usb": {
                key: {
                    "usb_id": value.usb_id,
                    "serial": value.serial,
                    "port": value.physical_port,
                }
                for key, value in sorted(host_usb.items())
            },
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()[:16]

    def _compose_snapshot(
        self,
        vms: Mapping[str, GuestRecord],
        lxcs: Mapping[str, GuestRecord],
        qga: Mapping[str, str],
    ) -> TopologySnapshot:
        pci = {
            address: replace(assignment, owner_name=vms[assignment.owner_id].name)
            for address, assignment in self._pci_assignments.items()
            if assignment.owner_id in vms
        }
        usb = self._build_usb_assignments(vms)
        host_usb = self._host_usb_devices(usb)
        gpu_owners = self._build_gpu_owners(vms, lxcs, pci)
        sources = tuple(
            replace(
                source,
                guest_name=vms.get(source.guest_id, GuestRecord("vm", source.guest_id, source.guest_name, "unknown")).name,
                guest_status=vms.get(source.guest_id, GuestRecord("vm", source.guest_id, source.guest_name, "unknown")).status,
            )
            for _key, source in sorted(self._storage_sources.items())
        )
        return TopologySnapshot(
            vms=dict(vms),
            lxcs=dict(lxcs),
            pci=pci,
            usb=usb,
            host_usb=host_usb,
            gpu_owners=gpu_owners,
            qga=dict(qga),
            storage_sources=sources,
            revision=self._revision(vms, lxcs, pci, usb, host_usb),
        )

    def full_scan(self) -> TopologySnapshot:
        vms, lxcs = self._guest_lists()
        try:
            pci_text = self._run(["lspci", "-Dnnk"], timeout=10)
        except Exception:
            pci_text = self._run(["lspci", "-Dnn"], timeout=10)
        self._gpu_catalog_text = pci_text
        self._pci_catalog = parse_lspci_catalog(pci_text)
        self._usb_inventory = self._scan_usb_inventory()

        self._vm_configs = {guest_id: self._read_config("vm", guest_id) for guest_id in vms}
        self._lxc_configs = {guest_id: self._read_config("lxc", guest_id) for guest_id in lxcs}
        self._refresh_native_pci(vms)

        qga: dict[str, str] = {}
        for guest_id, guest in vms.items():
            config = self._vm_configs.get(guest_id, "")
            qga[guest_id] = self._qga_state(guest, config, force=True)
            devices = tuple(
                assignment.device for assignment in self._pci_assignments.values()
                if assignment.owner_id == guest_id
            )
            self._probe_guest_storage(guest, devices, qga[guest_id])

        self._snapshot = self._compose_snapshot(vms, lxcs, qga)
        return self._snapshot

    def rescan_guest(self, kind: str, guest_id: str) -> None:
        if self._snapshot is None:
            self.full_scan()
            return
        if kind not in {"vm", "lxc"}:
            raise ValueError(f"unsupported guest kind: {kind}")

        vms = dict(self._snapshot.vms)
        lxcs = dict(self._snapshot.lxcs)
        qga = dict(self._snapshot.qga)
        if kind == "vm":
            guest = vms.get(guest_id)
            if guest is None:
                return
            config = self._read_config("vm", guest_id)
            self._vm_configs[guest_id] = config
            self._refresh_native_pci(vms, (guest_id,))
            qga[guest_id] = self._qga_state(guest, config, force=True)
            devices = tuple(
                assignment.device for assignment in self._pci_assignments.values()
                if assignment.owner_id == guest_id
            )
            self._probe_guest_storage(guest, devices, qga[guest_id])
        else:
            guest = lxcs.get(guest_id)
            if guest is None:
                return
            config = self._read_config("lxc", guest_id)
            self._lxc_configs[guest_id] = config

        self._snapshot = self._compose_snapshot(vms, lxcs, qga)

    def poll_guest_status(self) -> GuestStatusSnapshot:
        current_vms, current_lxcs = self._guest_lists()
        if self._snapshot is None:
            self.full_scan()
            assert self._snapshot is not None
            return GuestStatusSnapshot(self._snapshot.vms, self._snapshot.lxcs, ())

        previous_vms = self._snapshot.vms
        previous_lxcs = self._snapshot.lxcs
        changed: list[tuple[str, str, str, str]] = []
        for kind, previous, current in (
            ("vm", previous_vms, current_vms),
            ("lxc", previous_lxcs, current_lxcs),
        ):
            ids = set(previous) | set(current)
            for guest_id in sorted(ids, key=lambda value: int(value) if value.isdigit() else value):
                old = previous.get(guest_id)
                new = current.get(guest_id)
                old_status = old.status if old else "missing"
                new_status = new.status if new else "missing"
                if old_status != new_status:
                    changed.append((kind, guest_id, old_status, new_status))

        qga = dict(self._snapshot.qga)
        for guest_id, guest in current_vms.items():
            if guest.status != "running" and guest_id in qga:
                qga[guest_id] = "unavailable" if _agent_enabled(self._vm_configs.get(guest_id, "")) else "disabled"

        self._snapshot = self._compose_snapshot(current_vms, current_lxcs, qga)

        for kind, guest_id, old_status, new_status in changed:
            if new_status == "running" and old_status != "running":
                self.rescan_guest(kind, guest_id)

        assert self._snapshot is not None
        return GuestStatusSnapshot(
            vms=self._snapshot.vms,
            lxcs=self._snapshot.lxcs,
            changed=tuple(changed),
        )

    def vm_storage_sources(self) -> tuple[GuestStorageSource, ...]:
        if self._snapshot is None:
            return ()
        return self._snapshot.storage_sources

    def gpu_catalog_text(self) -> str:
        return self._gpu_catalog_text

    def gpu_owners(self) -> Mapping[str, GpuOwner]:
        return {} if self._snapshot is None else self._snapshot.gpu_owners

    def qga_state(self, guest_id: str) -> str:
        if self._snapshot is None:
            return "unknown"
        return self._snapshot.qga.get(guest_id, "unknown")

    def guest_status(self, guest_id: str) -> str:
        if self._snapshot is None:
            return "unknown"
        guest = self._snapshot.vms.get(guest_id) or self._snapshot.lxcs.get(guest_id)
        return guest.status if guest is not None else "unknown"

    def guest_payload(self) -> dict[str, object]:
        if self._snapshot is None:
            return {"vms": {}, "lxcs": {}, "summary": {"vms": _summary({}), "lxcs": _summary({})}}
        vms: dict[str, object] = {}
        for guest_id, guest in self._snapshot.vms.items():
            config = self._vm_configs.get(guest_id, "")
            passthrough_count = (
                sum(1 for item in self._snapshot.pci.values() if item.owner_id == guest_id)
                + sum(1 for item in self._snapshot.usb.values() if item.owner_id == guest_id)
            )
            vms[guest_id] = {
                "kind": "vm",
                "guest_id": guest_id,
                "name": guest.name,
                "status": guest.status,
                "agent_enabled": _agent_enabled(config),
                "qemu_agent": self._snapshot.qga.get(guest_id, "unknown"),
                "passthrough_count": passthrough_count,
            }
        lxcs: dict[str, object] = {}
        for guest_id, guest in self._snapshot.lxcs.items():
            passthrough_count = sum(
                1
                for owner in self._snapshot.gpu_owners.values()
                if owner.source_type == "lxc" and owner.source_id and guest_id in owner.source_id.split(",")
            )
            lxcs[guest_id] = {
                "kind": "lxc",
                "guest_id": guest_id,
                "name": guest.name,
                "status": guest.status,
                "agent_enabled": None,
                "qemu_agent": "not_applicable",
                "passthrough_count": passthrough_count,
            }
        return {
            "vms": vms,
            "lxcs": lxcs,
            "summary": {"vms": _summary(self._snapshot.vms), "lxcs": _summary(self._snapshot.lxcs)},
        }
