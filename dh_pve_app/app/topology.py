from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, replace
from typing import Callable, Mapping

from .collectors.gpu import GpuOwner, GuestInfo, parse_lxc_gpu_owners, read_dri_pci_map
from .collectors.guests import (
    GuestBlockDevice,
    GuestRecord,
    PassthroughDevice,
    is_physical_guest_disk,
    parse_hostpci,
    parse_lspci_catalog,
    parse_pct_list,
    parse_qga_lsblk,
    parse_qm_list,
)

Runner = Callable[..., str]


@dataclass(frozen=True)
class PciAssignment:
    owner_kind: str
    owner_id: str
    owner_name: str
    device: PassthroughDevice


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
    ) -> None:
        self.runner = runner
        self._fixed_dri_to_pci = dict(dri_to_pci) if dri_to_pci is not None else None
        self.now_monotonic = now_monotonic
        self._snapshot: TopologySnapshot | None = None
        self._vm_configs: dict[str, str] = {}
        self._lxc_configs: dict[str, str] = {}
        self._pci_catalog: dict[str, dict[str, str]] = {}
        self._qga_last_probe: dict[str, float] = {}
        self._storage_sources: dict[tuple[str, str], GuestStorageSource] = {}

    @property
    def snapshot(self) -> TopologySnapshot | None:
        return self._snapshot

    def _run(self, argv: list[str], *, timeout: float = 20.0, check: bool = True) -> str:
        return self.runner(argv, timeout=timeout, check=check)

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

        hostpci = ",".join(item.config_key for item in storage_devices)
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

        # An authoritative successful guest inventory may remove paths that no
        # longer exist inside this guest. Offline/QGA failures never reach here
        # and therefore preserve the last known physical source.
        for key in list(self._storage_sources):
            if key[0] == guest.guest_id and key not in seen:
                self._storage_sources.pop(key, None)

    def _build_pci_assignments(
        self,
        vms: Mapping[str, GuestRecord],
    ) -> dict[str, PciAssignment]:
        result: dict[str, PciAssignment] = {}
        for guest_id, config in self._vm_configs.items():
            guest = vms.get(guest_id, GuestRecord("vm", guest_id, f"VM {guest_id}", "unknown"))
            for device in parse_hostpci(config, self._pci_catalog):
                result[device.pci_address] = PciAssignment(
                    owner_kind="vm",
                    owner_id=guest_id,
                    owner_name=guest.name,
                    device=device,
                )
        return result

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
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()[:16]

    def _compose_snapshot(
        self,
        vms: Mapping[str, GuestRecord],
        lxcs: Mapping[str, GuestRecord],
        qga: Mapping[str, str],
    ) -> TopologySnapshot:
        pci = self._build_pci_assignments(vms)
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
            gpu_owners=gpu_owners,
            qga=dict(qga),
            storage_sources=sources,
            revision=self._revision(vms, lxcs, pci),
        )

    def full_scan(self) -> TopologySnapshot:
        vms = parse_qm_list(self._run(["qm", "list"], timeout=10))
        lxcs = parse_pct_list(self._run(["pct", "list"], timeout=10))
        self._pci_catalog = parse_lspci_catalog(self._run(["lspci", "-Dnn"], timeout=10))

        self._vm_configs = {}
        for guest_id in vms:
            try:
                self._vm_configs[guest_id] = self._run(["qm", "config", guest_id], timeout=10)
            except Exception:
                self._vm_configs[guest_id] = ""

        self._lxc_configs = {}
        for guest_id in lxcs:
            try:
                self._lxc_configs[guest_id] = self._run(["pct", "config", guest_id], timeout=10)
            except Exception:
                self._lxc_configs[guest_id] = ""

        qga: dict[str, str] = {}
        for guest_id, guest in vms.items():
            config = self._vm_configs.get(guest_id, "")
            qga[guest_id] = self._qga_state(guest, config, force=True)
            devices = parse_hostpci(config, self._pci_catalog)
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
            try:
                config = self._run(["qm", "config", guest_id], timeout=10)
            except Exception:
                config = self._vm_configs.get(guest_id, "")
            self._vm_configs[guest_id] = config
            qga[guest_id] = self._qga_state(guest, config, force=True)
            devices = parse_hostpci(config, self._pci_catalog)
            self._probe_guest_storage(guest, devices, qga[guest_id])
        else:
            guest = lxcs.get(guest_id)
            if guest is None:
                return
            try:
                self._lxc_configs[guest_id] = self._run(["pct", "config", guest_id], timeout=10)
            except Exception:
                pass

        self._snapshot = self._compose_snapshot(vms, lxcs, qga)

    def poll_guest_status(self) -> GuestStatusSnapshot:
        current_vms = parse_qm_list(self._run(["qm", "list"], timeout=10))
        current_lxcs = parse_pct_list(self._run(["pct", "list"], timeout=10))
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
            passthrough_count = sum(1 for item in self._snapshot.pci.values() if item.owner_id == guest_id)
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
