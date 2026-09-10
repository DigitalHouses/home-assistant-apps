from __future__ import annotations

import json
import platform
import re
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .app import CollectorSample
from .collectors.cooling import collect_fans
from .collectors.cpu import (
    CpuTimes,
    cpu_usage_percent,
    parse_lscpu,
    read_cpu_frequency,
    read_cpu_temperature,
    read_cpu_times,
    read_throttle_counters,
    thermal_throttling_active,
)
from .collectors.disks import stable_disk_id
from .collectors.gpu import (
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
from .collectors.host import build_hardware_identity, parse_pve_manager_version
from .collectors.memory import collect_memory, collect_memory_inventory
from .collectors.smart import SmartSnapshot, parse_smart_json
from .collectors.storage import parse_pvesm_status
from .daily_disk_stats import DailyDiskStats, update_daily_stats
from .disk_health import evaluate_disk_health
from .publish_policy import MetricValue
from .state_store import StateStore


def _run(argv: list[str], *, timeout: float = 20.0, check: bool = True) -> str:
    result = subprocess.run(
        argv,
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout


def _read(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _gib_from_kib(value: int) -> float:
    return round(value / (1024 * 1024), 2)


def _metric(value: object, policy: str) -> MetricValue:
    return MetricValue(value=value, policy=policy)


def _parse_guest_list(text: str, kind: str) -> dict[str, GuestInfo]:
    guests: dict[str, GuestInfo] = {}
    for raw in text.splitlines():
        parts = raw.split()
        if not parts or not parts[0].isdigit():
            continue
        guest_id = parts[0]
        if kind == "vm":
            name = parts[1] if len(parts) > 1 else f"VM {guest_id}"
            status = parts[2] if len(parts) > 2 else "unknown"
        else:
            status = parts[1] if len(parts) > 1 else "unknown"
            name = parts[-1] if len(parts) > 2 else f"LXC {guest_id}"
        guests[guest_id] = GuestInfo(guest_id, name, status)
    return guests


def _guest_configs(directory: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not directory.exists():
        return result
    for path in directory.glob("*.conf"):
        try:
            result[path.stem] = path.read_text(encoding="utf-8")
        except OSError:
            continue
    return result


def _checkpoint(snapshot: SmartSnapshot) -> dict[str, int | float]:
    names = (
        "media_errors",
        "reallocated_sectors",
        "pending_sectors",
        "offline_uncorrectable",
        "uncorrectable_errors",
        "program_failures",
        "erase_failures",
        "runtime_bad_blocks",
        "unsafe_shutdowns",
    )
    result: dict[str, int | float] = {}
    for name in names:
        value = getattr(snapshot, name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[name] = value
    return result


class ProductionCollectors:
    def __init__(
        self,
        *,
        node_name: str,
        disk_state_store: StateStore,
        sys_root: Path = Path("/sys"),
        proc_root: Path = Path("/proc"),
        pve_root: Path = Path("/etc/pve"),
    ) -> None:
        self.node_name = node_name
        self.disk_state_store = disk_state_store
        self.sys_root = sys_root
        self.proc_root = proc_root
        self.pve_root = pve_root
        self._cpu_previous: CpuTimes | None = None
        self._throttle_previous = None

    def host(self) -> CollectorSample:
        dmi_dir = self.sys_root / "class" / "dmi" / "id"
        values = {
            name: _read(dmi_dir / name)
            for name in (
                "sys_vendor",
                "product_name",
                "product_version",
                "board_vendor",
                "board_name",
                "board_version",
            )
        }
        hardware = build_hardware_identity(values)
        pve_text = _run(["pveversion", "-v"], timeout=15)
        topology = parse_lscpu(_run(["lscpu"], timeout=10))
        try:
            memory_inventory = collect_memory_inventory()
        except Exception:
            memory_inventory = None
        uptime_seconds = None
        uptime_raw = _read(self.proc_root / "uptime")
        if uptime_raw:
            try:
                uptime_seconds = round(float(uptime_raw.split()[0]), 1)
            except (ValueError, IndexError):
                pass
        boot_time = None
        stat_raw = _read(self.proc_root / "stat")
        if stat_raw:
            match = re.search(r"(?m)^btime\s+(\d+)$", stat_raw)
            if match:
                boot_time = int(match.group(1))
        data = {
            "node_name": self.node_name,
            "hostname": platform.node(),
            "kernel_version": platform.release(),
            "proxmox_version": parse_pve_manager_version(pve_text),
            "manufacturer": hardware.manufacturer,
            "model": hardware.model,
            "product_version": hardware.product_version,
            "board_vendor": hardware.board_vendor,
            "board_model": hardware.board_model,
            "board_version": hardware.board_version,
            "cpu": asdict(topology),
            "memory_inventory": asdict(memory_inventory) if memory_inventory is not None else None,
            "uptime_seconds": uptime_seconds,
            "boot_time_epoch": boot_time,
        }
        fingerprint = (
            data["proxmox_version"], data["kernel_version"], data["manufacturer"],
            data["model"], topology.model, topology.cores, topology.threads,
        )
        return CollectorSample(data=data, metrics={"inventory": _metric(repr(fingerprint), "discrete")})

    def cpu(self) -> CollectorSample:
        current_times = read_cpu_times(self.proc_root / "stat")
        usage = cpu_usage_percent(self._cpu_previous, current_times) if self._cpu_previous is not None else None
        self._cpu_previous = current_times
        temperature = read_cpu_temperature(self.sys_root)
        frequency = read_cpu_frequency(self.sys_root)
        throttles = read_throttle_counters(self.sys_root)
        throttling = thermal_throttling_active(self._throttle_previous, throttles)
        self._throttle_previous = throttles
        data = {
            "usage_percent": usage,
            "temperature_c": temperature,
            "frequency": asdict(frequency),
            "throttling_active": throttling,
            "throttling": asdict(throttles),
        }
        metrics = {"throttling_active": _metric(throttling, "discrete")}
        if usage is not None:
            metrics["usage_percent"] = _metric(usage, "cpu_percent")
        if temperature is not None:
            metrics["temperature_c"] = _metric(temperature, "temperature_c")
        if frequency.average_mhz is not None:
            metrics["frequency_mhz"] = _metric(frequency.average_mhz, "frequency_mhz")
        return CollectorSample(data=data, metrics=metrics)

    def memory(self) -> CollectorSample:
        snapshot = collect_memory(self.proc_root / "meminfo")
        data = {
            **asdict(snapshot),
            "total_gib": _gib_from_kib(snapshot.total_kib),
            "used_gib": _gib_from_kib(snapshot.used_kib),
            "available_gib": _gib_from_kib(snapshot.available_kib),
            "swap_total_gib": _gib_from_kib(snapshot.swap_total_kib),
            "swap_used_gib": _gib_from_kib(snapshot.swap_used_kib),
        }
        return CollectorSample(
            data=data,
            metrics={
                "usage_percent": _metric(snapshot.usage_percent, "memory_percent"),
                "swap_usage_percent": _metric(snapshot.swap_usage_percent, "memory_percent"),
            },
        )

    def storage(self) -> CollectorSample:
        items = parse_pvesm_status(_run(["pvesm", "status"], timeout=20))
        data = {item.name: asdict(item) for item in items}
        metrics = {
            f"{item.name}.usage_percent": _metric(item.usage_percent, "storage_percent")
            for item in items
        }
        return CollectorSample(data=data, metrics=metrics)

    @staticmethod
    def _smart_scan_entries(text: str) -> tuple[tuple[str, ...], ...]:
        result = []
        for raw in text.splitlines():
            command = raw.split("#", 1)[0].strip()
            if not command:
                continue
            parts = command.split()
            if parts and parts[0].startswith("/dev/"):
                result.append(tuple(parts))
        return tuple(result)

    def smart(self) -> CollectorSample:
        scan = _run(["smartctl", "--scan-open"], timeout=20, check=False)
        entries = self._smart_scan_entries(scan)
        persisted = self.disk_state_store.load()
        previous = persisted.get("checkpoints", {})
        daily_raw = persisted.get("daily", {})
        previous = previous if isinstance(previous, dict) else {}
        daily_raw = daily_raw if isinstance(daily_raw, dict) else {}
        data = {}
        metrics = {}
        checkpoints = {}
        daily_next = {}
        for entry in entries:
            device = entry[0]
            raw = _run(["smartctl", "-a", "-j", *entry], timeout=25)
            snap = parse_smart_json(json.loads(raw), device)
            disk_id = stable_disk_id(
                wwn=snap.wwn, serial=snap.serial, path=device,
                model=snap.model, size_bytes=snap.capacity_bytes,
            )
            prior = previous.get(disk_id)
            prior = prior if isinstance(prior, dict) else None
            health = evaluate_disk_health(snap, prior)
            current_daily = None
            item = daily_raw.get(disk_id)
            if isinstance(item, dict):
                try:
                    current_daily = DailyDiskStats(**item)
                except TypeError:
                    current_daily = None
            daily, _completed = update_daily_stats(current_daily, snap, datetime.now().astimezone())
            data[disk_id] = {
                **asdict(snap),
                "disk_id": disk_id,
                "health_state": health.state.value,
                "health_reasons": list(health.reasons),
                "recommendation": health.recommendation,
                "daily": asdict(daily),
            }
            metrics[f"{disk_id}.health"] = _metric(health.state.value, "discrete")
            for field in (
                "media_errors", "reallocated_sectors", "pending_sectors",
                "offline_uncorrectable", "uncorrectable_errors", "program_failures",
                "erase_failures", "runtime_bad_blocks", "unsafe_shutdowns",
            ):
                value = getattr(snap, field)
                if value is not None:
                    metrics[f"{disk_id}.{field}"] = _metric(value, "counter")
            if snap.temperature_c is not None:
                metrics[f"{disk_id}.temperature_c"] = _metric(snap.temperature_c, "temperature_c")
            if snap.wear_used_percent is not None:
                metrics[f"{disk_id}.wear_used_percent"] = _metric(snap.wear_used_percent, "discrete")
            checkpoints[disk_id] = _checkpoint(snap)
            daily_next[disk_id] = asdict(daily)
        self.disk_state_store.save({"checkpoints": checkpoints, "daily": daily_next})
        return CollectorSample(data=data, metrics=metrics)

    def _gpu_context(self):
        lspci = _run(["lspci", "-Dnnk"], timeout=10)
        vm_configs = _guest_configs(self.pve_root / "qemu-server")
        lxc_configs = _guest_configs(self.pve_root / "lxc")
        try:
            vm_guests = _parse_guest_list(_run(["qm", "list"], timeout=10), "vm")
        except Exception:
            vm_guests = {}
        try:
            lxc_guests = _parse_guest_list(_run(["pct", "list"], timeout=10), "lxc")
        except Exception:
            lxc_guests = {}
        vm_owners = parse_vm_gpu_owners(vm_configs, vm_guests)
        lxc_owners = parse_lxc_gpu_owners(lxc_configs, lxc_guests, read_dri_pci_map(self.sys_root))
        return lspci, vm_guests, vm_owners, lxc_owners

    def gpu(self) -> CollectorSample:
        lspci, vm_guests, vm_owners, lxc_owners = self._gpu_context()
        inventory = parse_lspci_gpus(lspci)
        temperatures = {}
        transcoding = {}
        for item in inventory:
            pci = item["pci_address"]
            temperature = read_gpu_temperature(pci, sys_root=self.sys_root)
            if temperature is not None:
                temperatures[pci] = temperature
            owner = vm_owners.get(pci) or lxc_owners.get(pci)
            if item["vendor_id"] != "0x8086":
                continue
            try:
                if owner and owner.source_type == "vm" and owner.source_id:
                    guest = vm_guests.get(owner.source_id)
                    if guest is None or guest.status != "running":
                        continue
                    guest_cmd = (
                        'command -v intel_gpu_top >/dev/null 2>&1 || exit 20; '
                        'raw="$(timeout 3s intel_gpu_top -J -s 1000 2>/dev/null)"; '
                        'rc=$?; [ "$rc" -eq 0 ] || [ "$rc" -eq 124 ] || exit "$rc"; '
                        '[ -n "$raw" ] || exit 21; printf "%s" "$raw"'
                    )
                    outer = _run(
                        ["qm", "guest", "exec", owner.source_id, "--", "/bin/sh", "-c", guest_cmd],
                        timeout=12,
                    )
                    transcoding[pci] = parse_qemu_guest_exec_transcoding(outer, owner.source_id)
                elif owner is None and item["kernel_driver"] == "i915":
                    raw = _run(["timeout", "3s", "intel_gpu_top", "-J", "-s", "1000"], timeout=5, check=False)
                    if raw.strip():
                        transcoding[pci] = dict(parse_intel_gpu_top_json(raw))
            except Exception:
                continue
        snapshots = build_gpu_snapshots(
            lspci, vm_owners=vm_owners, lxc_owners=lxc_owners,
            temperatures=temperatures, transcoding=transcoding, hostname=platform.node(),
        )
        data = {item.gpu_id: asdict(item) for item in snapshots}
        metrics = {}
        for item in snapshots:
            metrics[f"{item.gpu_id}.owner"] = _metric(
                f"{item.connection}:{item.source_type}:{item.source_id}", "discrete"
            )
            if item.temperature_c is not None:
                metrics[f"{item.gpu_id}.temperature_c"] = _metric(item.temperature_c, "temperature_c")
            if item.transcoding_load_percent is not None:
                metrics[f"{item.gpu_id}.transcoding_load_percent"] = _metric(
                    item.transcoding_load_percent, "gpu_percent"
                )
        return CollectorSample(data=data, metrics=metrics)

    def fans(self) -> CollectorSample:
        fans = collect_fans(self.sys_root / "class" / "hwmon")
        data = {fan.fan_id: asdict(fan) for fan in fans}
        metrics = {
            f"{fan.fan_id}.rpm": _metric(fan.rpm, "fan_rpm")
            for fan in fans if fan.rpm is not None
        }
        return CollectorSample(data=data, metrics=metrics)

    def mapping(self):
        return {
            "host": self.host,
            "cpu": self.cpu,
            "memory": self.memory,
            "storage": self.storage,
            "smart": self.smart,
            "gpu": self.gpu,
            "fans": self.fans,
        }
