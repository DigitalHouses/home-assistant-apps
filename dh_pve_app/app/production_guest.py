from __future__ import annotations

import json
import platform
import re
from dataclasses import asdict

from . import production as base_production
from .app import CollectorSample
from .collectors.gpu import (
    build_gpu_snapshots,
    parse_intel_gpu_top_json,
    parse_lspci_gpus,
    parse_qemu_guest_exec_transcoding,
    read_gpu_temperature,
)
from .production_v1 import ResilientProductionCollectors
from .publish_policy import MetricValue


def _metric(value: object, policy: str) -> MetricValue:
    return MetricValue(value=value, policy=policy)


def _pci_object_id(pci: str) -> str:
    return "pci_" + re.sub(r"[^a-z0-9]+", "_", pci.lower()).strip("_")


class GuestAwareProductionCollectors(ResilientProductionCollectors):
    """Production collectors backed by one shared guest/passthrough topology."""

    def topology_inventory(self) -> CollectorSample:
        if self.topology is None:
            return CollectorSample(data={"revision": None, "assignments": {}}, metrics={})
        snapshot = self.topology.full_scan()
        assignments: dict[str, dict[str, object]] = {}
        for pci, assignment in sorted(snapshot.pci.items()):
            device = assignment.device
            assignments[_pci_object_id(pci)] = {
                "connection": "passthrough_pci",
                "owner_kind": assignment.owner_kind,
                "owner_id": assignment.owner_id,
                "owner_name": assignment.owner_name,
                "config_key": device.config_key,
                "pci_address": device.pci_address,
                "pci_class": device.pci_class,
                "class_name": device.class_name,
                "model": device.model,
            }

        # Preserve the legacy shared /dev/dri -> LXC mapping as topology too.
        # It is not hostpci and therefore does not exist in snapshot.pci.
        for pci, owner in sorted(snapshot.gpu_owners.items()):
            if owner.source_type != "lxc" or _pci_object_id(pci) in assignments:
                continue
            assignments[_pci_object_id(pci)] = {
                "connection": owner.connection,
                "owner_kind": "lxc",
                "owner_id": owner.source_id or "unknown",
                "owner_name": owner.source_name or "Unknown",
                "config_key": ",".join(owner.dri_devices) if owner.dri_devices else "dri",
                "pci_address": pci,
                "pci_class": "03",
                "class_name": "Graphics controller",
                "model": pci,
            }

        data = {"revision": snapshot.revision, "assignments": assignments}
        return CollectorSample(
            data=data,
            metrics={"revision": _metric(snapshot.revision, "discrete")},
        )

    def guests(self) -> CollectorSample:
        if self.topology is None:
            return CollectorSample(
                data={"vms": {}, "lxcs": {}, "summary": {}},
                metrics={},
            )
        status = self.topology.poll_guest_status()
        data = self.topology.guest_payload()
        metrics: dict[str, MetricValue] = {}
        for kind, records in (("vm", status.vms), ("lxc", status.lxcs)):
            for guest_id, guest in records.items():
                metrics[f"{kind}.{guest_id}.status"] = _metric(guest.status, "discrete")
        summary = data.get("summary", {})
        if isinstance(summary, dict):
            for plural in ("vms", "lxcs"):
                raw = summary.get(plural)
                if isinstance(raw, dict):
                    metrics[f"{plural}.running"] = _metric(
                        int(raw.get("running", 0) or 0), "discrete"
                    )
        return CollectorSample(data=data, metrics=metrics)

    def _guest_gpu_telemetry(self, owner, guest_cmd: str) -> dict[str, object] | None:
        if self.topology is None or not owner.source_id:
            return None
        if self.topology.guest_status(owner.source_id) != "running":
            return None
        if self.topology.qga_state(owner.source_id) != "available":
            return None

        guest_exec = getattr(self.topology, "guest_exec", None)
        if callable(guest_exec):
            raw = guest_exec(owner.source_id, guest_cmd, timeout=12.0)
            outer = json.dumps({"exitcode": 0, "out-data": raw})
        else:
            outer = base_production._run(
                [
                    "qm", "guest", "exec", owner.source_id,
                    "--", "/bin/sh", "-c", guest_cmd,
                ],
                timeout=12,
            )
        return dict(parse_qemu_guest_exec_transcoding(outer, owner.source_id))

    def gpu(self) -> CollectorSample:
        if self.topology is None:
            return super().gpu()

        lspci = base_production._run(["lspci", "-Dnnk"], timeout=10)
        inventory = parse_lspci_gpus(lspci)
        owners = dict(self.topology.gpu_owners())
        vm_owners = {pci: owner for pci, owner in owners.items() if owner.source_type == "vm"}
        lxc_owners = {pci: owner for pci, owner in owners.items() if owner.source_type == "lxc"}

        temperatures: dict[str, float] = {}
        transcoding: dict[str, dict[str, object]] = {}
        for item in inventory:
            pci = item["pci_address"]
            temperature = read_gpu_temperature(pci, sys_root=self.sys_root)
            if temperature is not None:
                temperatures[pci] = temperature

            if item["vendor_id"] != "0x8086":
                continue
            owner = owners.get(pci)
            try:
                if owner and owner.source_type == "vm" and owner.source_id:
                    guest_cmd = (
                        'command -v intel_gpu_top >/dev/null 2>&1 || exit 20; '
                        'raw="$(timeout 3s intel_gpu_top -J -s 1000 2>/dev/null)"; '
                        'rc=$?; [ "$rc" -eq 0 ] || [ "$rc" -eq 124 ] || exit "$rc"; '
                        '[ -n "$raw" ] || exit 21; printf "%s" "$raw"'
                    )
                    metrics = self._guest_gpu_telemetry(owner, guest_cmd)
                    if metrics is not None:
                        transcoding[pci] = metrics
                elif owner is None and item["kernel_driver"] == "i915":
                    raw = base_production._run(
                        ["timeout", "3s", "intel_gpu_top", "-J", "-s", "1000"],
                        timeout=5,
                        check=False,
                    )
                    if raw.strip():
                        transcoding[pci] = dict(parse_intel_gpu_top_json(raw))
            except Exception:
                continue

        snapshots = build_gpu_snapshots(
            lspci,
            vm_owners=vm_owners,
            lxc_owners=lxc_owners,
            temperatures=temperatures,
            transcoding=transcoding,
            hostname=platform.node(),
        )
        data = {item.gpu_id: asdict(item) for item in snapshots}
        metrics: dict[str, MetricValue] = {}
        for item in snapshots:
            metrics[f"{item.gpu_id}.owner"] = _metric(
                f"{item.connection}:{item.source_type}:{item.source_id}", "discrete"
            )
            if item.temperature_c is not None:
                metrics[f"{item.gpu_id}.temperature_c"] = _metric(
                    item.temperature_c, "temperature_c"
                )
            if item.transcoding_load_percent is not None:
                metrics[f"{item.gpu_id}.transcoding_load_percent"] = _metric(
                    item.transcoding_load_percent, "gpu_percent"
                )
        return CollectorSample(data=data, metrics=metrics)

    def mapping(self):
        if self.topology is None:
            return super().mapping()
        return {
            "topology": self.topology_inventory,
            "guests": self.guests,
            "host": self.host,
            "cpu": self.cpu,
            "memory": self.memory,
            "storage": self.storage,
            "smart": self.smart,
            "gpu": self.gpu,
            "fans": self.fans,
        }
