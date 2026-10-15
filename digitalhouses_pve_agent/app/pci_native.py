"""Validate JSON from the read-only Proxmox PCI helper.

The helper uses PVE::QemuServer::PCI::parse_hostpci, not an independent
hostpci grammar or an interpretation of lspci's human-readable output.
"""
from __future__ import annotations

import json
import re
from typing import Mapping

from .collectors.guests import PassthroughDevice

_PCI_ID = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]$")
_HEX_ID = re.compile(r"^0x[0-9a-fA-F]{4}$")
_HEX_CLASS = re.compile(r"^0x[0-9a-fA-F]{6}$")
_HOSTPCI_KEY = re.compile(r"^hostpci[0-9]+$")


def parse_native_pci_inventory(
    raw: str,
    requested_vmids: set[str],
    catalog: Mapping[str, Mapping[str, str]],
) -> tuple[dict[str, tuple[str, PassthroughDevice]], dict[str, str]]:
    """Return PCI BDF -> (VMID, device) and per-VM errors.

    Malformed or contradictory native output raises ValueError; callers must
    preserve the last trustworthy topology instead of guessing ownership.
    """
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ValueError("unsupported native PCI inventory schema")
    devices, failures = payload.get("devices"), payload.get("errors")
    if not isinstance(devices, list) or not isinstance(failures, list):
        raise ValueError("native PCI inventory is missing devices/errors arrays")

    errors: dict[str, str] = {}
    for item in failures:
        if not isinstance(item, dict) or not isinstance(item.get("guest_id"), str):
            raise ValueError("invalid native PCI error")
        vmid = item["guest_id"]
        if vmid not in requested_vmids:
            raise ValueError("native PCI error has unexpected VMID")
        message = item.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("native PCI error has no message")
        errors[vmid] = (errors.get(vmid, "") + "; " if vmid in errors else "") + message.strip()

    parsed: dict[str, tuple[str, PassthroughDevice]] = {}
    for item in devices:
        if not isinstance(item, dict):
            raise ValueError("native PCI device is not an object")
        vmid, key, pci, pci_class = (item.get(name) for name in (
            "guest_id", "config_key", "pci_address", "pci_class"
        ))
        if (
            not isinstance(vmid, str) or vmid not in requested_vmids
            or not isinstance(key, str) or not _HOSTPCI_KEY.fullmatch(key)
            or not isinstance(pci, str) or not _PCI_ID.fullmatch(pci)
            or not isinstance(pci_class, str) or not _HEX_CLASS.fullmatch(pci_class)
        ):
            raise ValueError("invalid native PCI device identity or class")
        pci = pci.lower()
        vendor, device = item.get("vendor_id"), item.get("device_id")
        if (
            not isinstance(vendor, str) or not _HEX_ID.fullmatch(vendor)
            or not isinstance(device, str) or not _HEX_ID.fullmatch(device)
        ):
            raise ValueError("invalid native PCI vendor/device ID")
        if pci in parsed:
            raise ValueError(f"duplicate native PCI BDF {pci}")
        meta = catalog.get(pci, {})
        parsed[pci] = (
            vmid,
            PassthroughDevice(
                config_key=key,
                pci_address=pci,
                pci_class=pci_class[2:6].lower(),
                class_name=str(meta.get("class_name") or "PCI device"),
                model=str(meta.get("model") or pci),
                vendor_id=vendor.lower(),
                device_id=device.lower(),
            ),
        )

    return parsed, errors
