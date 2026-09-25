from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

PCI_RE = re.compile(r"^(?P<pci>[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7])\s+.*?\[(?P<class>[0-9a-fA-F]{4})\]:\s+(?P<model>.+?)\s+\[(?P<vendor>[0-9a-fA-F]{4}):(?P<device>[0-9a-fA-F]{4})\](?:\s+\(rev [^)]+\))?$")
HOSTPCI_RE = re.compile(r"^hostpci\d+:\s*(?P<pci>(?:[0-9a-fA-F]{4}:)?[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7])(?:,.*)?$", re.MULTILINE)
DRI_RE = re.compile(r"/dev/dri/(?P<node>card\d+|renderD\d+)")


@dataclass(frozen=True)
class GuestInfo:
    guest_id: str
    name: str
    status: str


@dataclass(frozen=True)
class GpuOwner:
    connection: str
    source_type: str
    source_id: str | None
    source_name: str | None
    source_status: str
    dri_devices: tuple[str, ...] = ()
    config: str | None = None


@dataclass(frozen=True)
class GpuSnapshot:
    gpu_id: str
    pci_address: str
    model: str
    display_name: str
    vendor_id: str
    device_id: str
    kernel_driver: str
    owner: str
    connection: str
    source_type: str
    source_id: str | None
    source_name: str | None
    source_status: str
    config: str | None
    dri_devices: tuple[str, ...]
    temperature_c: float | None
    transcoding_supported: bool
    transcoding_available: bool
    transcoding_load_percent: float | None
    video_busy_percent: float | None
    render_busy_percent: float | None
    video_enhance_busy_percent: float | None
    rc6_percent: float | None
    transcoding_sample_count: int
    transcoding_source: str | None
    transcoding_vm_id: str | None


def normalize_pci(value: str) -> str:
    value = value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", value):
        return "0000:" + value
    if re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", value):
        return value
    raise ValueError(f"invalid PCI address: {value}")


def _display_name(model: str) -> str:
    value = model
    value = re.sub(r"^Intel Corporation\s+", "Intel ", value)
    value = re.sub(r"^NVIDIA Corporation\s+", "NVIDIA ", value)
    value = re.sub(r"^Advanced Micro Devices, Inc\. \[AMD/ATI\]\s+", "AMD ", value)
    value = value.replace("[", "").replace("]", "")
    return " ".join(value.split())


def parse_lspci_gpus(text: str) -> tuple[dict[str, str], ...]:
    result: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        match = PCI_RE.match(line)
        if match:
            if match.group("class").lower() not in {"0300", "0302", "0380"}:
                current = None
                continue
            current = {
                "pci_address": match.group("pci").lower(),
                "model": match.group("model").strip(),
                "display_name": _display_name(match.group("model").strip()),
                "vendor_id": "0x" + match.group("vendor").lower(),
                "device_id": "0x" + match.group("device").lower(),
                "kernel_driver": "unbound",
            }
            result.append(current)
            continue
        if current is not None:
            stripped = line.strip()
            if stripped.startswith("Kernel driver in use:"):
                current["kernel_driver"] = stripped.split(":", 1)[1].strip()
    return tuple(result)


def parse_vm_gpu_owners(configs: Mapping[str, str], guests: Mapping[str, GuestInfo]) -> dict[str, GpuOwner]:
    owners: dict[str, GpuOwner] = {}
    for vmid, config in configs.items():
        guest = guests.get(vmid, GuestInfo(vmid, f"VM {vmid}", "unknown"))
        for match in HOSTPCI_RE.finditer(config):
            pci = normalize_pci(match.group("pci"))
            line = match.group(0).strip()
            owners[pci] = GpuOwner(
                connection="passthrough_pci",
                source_type="vm",
                source_id=vmid,
                source_name=guest.name,
                source_status=guest.status,
                config=line,
            )
    return owners


def parse_lxc_gpu_owners(
    configs: Mapping[str, str],
    guests: Mapping[str, GuestInfo],
    dri_to_pci: Mapping[str, str],
) -> dict[str, GpuOwner]:
    grouped: dict[str, dict[str, object]] = {}
    for ctid, config in configs.items():
        guest = guests.get(ctid, GuestInfo(ctid, f"LXC {ctid}", "unknown"))
        for match in DRI_RE.finditer(config):
            node = match.group("node")
            pci_raw = dri_to_pci.get(node)
            if not pci_raw:
                continue
            pci = normalize_pci(pci_raw)
            item = grouped.setdefault(pci, {"ids": [], "names": [], "statuses": [], "nodes": []})
            ids = item["ids"]
            names = item["names"]
            statuses = item["statuses"]
            nodes = item["nodes"]
            assert isinstance(ids, list) and isinstance(names, list)
            assert isinstance(statuses, list) and isinstance(nodes, list)
            if ctid not in ids:
                ids.append(ctid)
                names.append(guest.name)
                statuses.append(guest.status)
            if node not in nodes:
                nodes.append(node)
    result: dict[str, GpuOwner] = {}
    for pci, item in grouped.items():
        ids = item["ids"]
        names = item["names"]
        statuses = item["statuses"]
        nodes = item["nodes"]
        assert all(isinstance(x, list) for x in (ids, names, statuses, nodes))
        result[pci] = GpuOwner(
            connection="shared_dri",
            source_type="lxc",
            source_id=",".join(ids),
            source_name=", ".join(names),
            source_status=", ".join(statuses),
            dri_devices=tuple(nodes),
        )
    return result


def parse_intel_gpu_top_json(text: str) -> dict[str, float | int | bool | str | None]:
    raw = text.strip().rstrip(",")
    if not raw:
        raise ValueError("empty intel_gpu_top output")
    # intel_gpu_top -J emits a stream of JSON objects separated by commas.
    try:
        parsed = json.loads(raw)
        samples = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        samples = json.loads("[" + raw + "]")
    full = [
        sample
        for sample in samples
        if isinstance(sample, dict)
        and float(sample.get("period", {}).get("duration", 0) or 0) >= 500
    ]
    if not full:
        raise ValueError("no full intel_gpu_top samples")

    def peak(prefix: str) -> float:
        values: list[float] = []
        for sample in full:
            engines = sample.get("engines", {})
            if not isinstance(engines, dict):
                continue
            for name, data in engines.items():
                if not str(name).startswith(prefix) or not isinstance(data, dict):
                    continue
                busy = data.get("busy")
                if isinstance(busy, (int, float)) and not isinstance(busy, bool):
                    values.append(max(0.0, min(100.0, float(busy))))
        return round(max(values, default=0.0), 1)

    rc6 = full[-1].get("rc6", {}).get("value")
    rc6_value = (
        round(max(0.0, min(100.0, float(rc6))), 1)
        if isinstance(rc6, (int, float)) and not isinstance(rc6, bool)
        else None
    )
    video = peak("Video/")
    return {
        "supported": True,
        "available": True,
        "transcoding_load_percent": video,
        "video_busy_percent": video,
        "render_busy_percent": peak("Render/3D/"),
        "video_enhance_busy_percent": peak("VideoEnhance/"),
        "rc6_percent": rc6_value,
        "sample_count": len(full),
        "source": "intel_gpu_top",
    }


def read_dri_pci_map(sys_root: Path = Path("/sys")) -> dict[str, str]:
    """Map DRM node names (card0/renderD128) to canonical PCI BDFs."""
    result: dict[str, str] = {}
    drm_root = sys_root / "class" / "drm"
    if not drm_root.exists():
        return result
    for node_path in sorted(drm_root.iterdir()):
        if not re.fullmatch(r"card\d+|renderD\d+", node_path.name):
            continue
        try:
            device_real = (node_path / "device").resolve(strict=True)
        except OSError:
            continue
        for part in reversed(device_real.parts):
            try:
                pci = normalize_pci(part)
            except ValueError:
                continue
            result[node_path.name] = pci
            break
    return result


def parse_qemu_guest_exec_transcoding(text: str, vmid: str) -> dict[str, object]:
    """Parse `qm guest exec` JSON and normalize intel_gpu_top telemetry."""
    try:
        outer = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid qemu guest exec JSON") from exc
    if not isinstance(outer, dict):
        raise ValueError("qemu guest exec result must be an object")
    exitcode = outer.get("exitcode")
    if not isinstance(exitcode, int) or isinstance(exitcode, bool) or exitcode != 0:
        raise ValueError(f"guest intel_gpu_top failed: exitcode={exitcode!r}")
    raw = outer.get("out-data")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("guest intel_gpu_top returned no data")
    metrics: dict[str, object] = dict(parse_intel_gpu_top_json(raw))
    metrics["source"] = "qemu_guest_agent_intel_gpu_top"
    metrics["vm_id"] = str(vmid)
    return metrics


def read_gpu_temperature(
    pci_address: str,
    *,
    sys_root: Path = Path("/sys"),
) -> float | None:
    """Return the hottest hwmon sensor attached to this PCI GPU.

    A passed-through GPU commonly has no host-visible hwmon node. That is a
    supported/normal state and returns None rather than failing the collector.
    """
    pci = normalize_pci(pci_address)
    pci_path = sys_root / "bus" / "pci" / "devices" / pci
    try:
        pci_real = pci_path.resolve(strict=True)
    except OSError:
        return None

    values: list[float] = []
    hwmon_root = sys_root / "class" / "hwmon"
    if not hwmon_root.exists():
        return None

    for hwmon in sorted(hwmon_root.glob("hwmon*")):
        device_link = hwmon / "device"
        try:
            device_real = device_link.resolve(strict=True)
        except OSError:
            continue
        try:
            attached = device_real == pci_real or pci_real in device_real.parents
        except RuntimeError:
            attached = False
        if not attached:
            continue
        for input_path in hwmon.glob("temp*_input"):
            try:
                raw = input_path.read_text(encoding="utf-8").strip()
                milli_c = int(raw)
            except (OSError, ValueError):
                continue
            values.append(round(milli_c / 1000.0, 1))

    return max(values) if values else None


def build_gpu_snapshots(
    lspci_text: str,
    *,
    vm_owners: Mapping[str, GpuOwner] | None = None,
    lxc_owners: Mapping[str, GpuOwner] | None = None,
    temperatures: Mapping[str, float] | None = None,
    transcoding: Mapping[str, Mapping[str, object]] | None = None,
    hostname: str = "pve",
) -> tuple[GpuSnapshot, ...]:
    vm_owners = vm_owners or {}
    lxc_owners = lxc_owners or {}
    temperatures = temperatures or {}
    transcoding = transcoding or {}
    snapshots: list[GpuSnapshot] = []
    for item in parse_lspci_gpus(lspci_text):
        pci = item["pci_address"]
        owner_info = vm_owners.get(pci) or lxc_owners.get(pci)
        if owner_info is None:
            driver = item["kernel_driver"]
            if driver == "vfio-pci":
                owner = "VFIO"
                connection = "passthrough_or_reserved"
                source_type = "unknown"
                source_id = None
                source_name = None
                source_status = "unknown"
                nodes = ()
            elif driver == "unbound":
                owner = "Unused"
                connection = "unbound"
                source_type = "host"
                source_id = None
                source_name = hostname
                source_status = "unknown"
                nodes = ()
            else:
                owner = "Host"
                connection = "host"
                source_type = "host"
                source_id = None
                source_name = hostname
                source_status = "running"
                nodes = ()
        else:
            source_type = owner_info.source_type
            source_id = owner_info.source_id
            source_name = owner_info.source_name
            source_status = owner_info.source_status
            connection = owner_info.connection
            nodes = owner_info.dri_devices
            owner = ("VM " if source_type == "vm" else "LXC ") + (source_id or "")
        tr = transcoding.get(pci, {})
        snapshots.append(
            GpuSnapshot(
                gpu_id="pci_" + pci.replace(":", "_").replace(".", "_"),
                pci_address=pci,
                model=item["model"],
                display_name=item["display_name"],
                vendor_id=item["vendor_id"],
                device_id=item["device_id"],
                kernel_driver=item["kernel_driver"],
                owner=owner,
                connection=connection,
                source_type=source_type,
                source_id=source_id,
                source_name=source_name,
                source_status=source_status,
                config=owner_info.config if owner_info is not None else None,
                dri_devices=tuple(nodes),
                temperature_c=temperatures.get(pci),
                transcoding_supported=bool(tr.get("supported", False)),
                transcoding_available=bool(tr.get("available", False)),
                transcoding_load_percent=_float_or_none(tr.get("transcoding_load_percent")),
                video_busy_percent=_float_or_none(tr.get("video_busy_percent")),
                render_busy_percent=_float_or_none(tr.get("render_busy_percent")),
                video_enhance_busy_percent=_float_or_none(tr.get("video_enhance_busy_percent")),
                rc6_percent=_float_or_none(tr.get("rc6_percent")),
                transcoding_sample_count=int(tr.get("sample_count", 0) or 0),
                transcoding_source=str(tr.get("source")) if tr.get("source") else None,
                transcoding_vm_id=(
                    str(tr.get("vm_id")) if tr.get("vm_id") is not None else None
                ),
            )
        )
    return tuple(snapshots)


def _float_or_none(value: object) -> float | None:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )
