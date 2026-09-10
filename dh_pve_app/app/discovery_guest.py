from __future__ import annotations

import json
from typing import Any, Mapping

from .config import AppConfig
from .discovery_metrics import _path, _sensor, _slug, build_full_discovery_payload
from .identity import HostIdentity
from .topics import build_topics


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def build_guest_aware_discovery_payload(
    config: AppConfig,
    identity: HostIdentity,
    *,
    version: str,
    inventory: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Extend the Phase-1 Discovery payload with read-only guest/topology entities."""
    inventory = inventory or {}
    payload = build_full_discovery_payload(
        config,
        identity,
        version=version,
        inventory=inventory,
    )
    components = payload["components"]
    topics = build_topics(config.mqtt, identity)

    def uid(component: str) -> str:
        return f"{topics.device_id}_{component}"

    guests = _mapping(inventory.get("guests"))
    for plural, kind, label in (("vms", "vm", "VM"), ("lxcs", "lxc", "LXC")):
        records = _mapping(guests.get(plural))
        for index, (guest_id_raw, raw) in enumerate(
            sorted(records.items(), key=lambda item: int(str(item[0])) if str(item[0]).isdigit() else str(item[0])),
            start=1,
        ):
            if not isinstance(raw, Mapping):
                continue
            guest_id = str(guest_id_raw)
            name = str(raw.get("name") or f"{label} {guest_id}")
            obj = _path("guests", plural, guest_id)
            key, item = _sensor(
                uid=uid,
                state_topic=topics.state,
                app_topic=topics.availability,
                key=f"{kind}_{_slug(guest_id)}_status",
                name=f"{label} {guest_id} {name}",
                entity_id=f"sensor.dh_pve_{kind}_{_slug(guest_id)}_status",
                expression=obj + ".status | default('unknown')",
                subsystem="guests",
                section="guests",
                subject=kind,
                metric="status",
                object_id=f"{kind}_{guest_id}",
                display_name=name,
                sort_key=f"700_{0 if kind == 'vm' else 1}_{index:03d}",
                entity_category="diagnostic",
                icon="mdi:server" if kind == "vm" else "mdi:package-variant-closed",
                extra_attrs={
                    "guest_id": json.dumps(guest_id),
                    "guest_kind": json.dumps(kind),
                    "passthrough_count": obj + ".passthrough_count | default(0)",
                    "qemu_agent": obj + ".qemu_agent | default('not_applicable')",
                },
            )
            components[key] = item

        summary = _mapping(_mapping(guests.get("summary")).get(plural))
        if summary or records:
            obj = _path("guests", "summary", plural)
            key, item = _sensor(
                uid=uid,
                state_topic=topics.state,
                app_topic=topics.availability,
                key=f"{plural}_summary",
                name="VMs" if kind == "vm" else "LXCs",
                entity_id="sensor.dh_pve_vms" if kind == "vm" else "sensor.dh_pve_lxcs",
                expression=obj + ".running | default(0)",
                subsystem="guests",
                section="guests",
                subject="summary",
                metric="running",
                object_id=plural,
                display_name="VMs" if kind == "vm" else "LXCs",
                sort_key=f"700_{0 if kind == 'vm' else 1}_000",
                entity_category="diagnostic",
                icon="mdi:server-multiple" if kind == "vm" else "mdi:package-variant",
                extra_attrs={
                    "total": obj + ".total | default(0)",
                    "running": obj + ".running | default(0)",
                    "paused": obj + ".paused | default(0)",
                    "stopped": obj + ".stopped | default(0)",
                    "unknown": obj + ".unknown | default(0)",
                },
            )
            components[key] = item

    topology = _mapping(inventory.get("topology"))
    assignments = _mapping(topology.get("assignments"))
    for index, (assignment_id_raw, raw) in enumerate(sorted(assignments.items()), start=1):
        if not isinstance(raw, Mapping):
            continue
        assignment_id = str(assignment_id_raw)
        slug = _slug(assignment_id)
        owner_kind = str(raw.get("owner_kind") or "unknown")
        owner_id = str(raw.get("owner_id") or "unknown")
        owner_name = str(raw.get("owner_name") or "Unknown")
        owner_label = f"{owner_kind.upper()} {owner_id}" if owner_kind in {"vm", "lxc"} else owner_name
        obj = _path("topology", "assignments", assignment_id)
        key, item = _sensor(
            uid=uid,
            state_topic=topics.state,
            app_topic=topics.availability,
            key=f"passthrough_{slug}",
            name=f"Passthrough {raw.get('pci_address') or assignment_id}",
            entity_id=f"sensor.dh_pve_passthrough_{slug}",
            expression=json.dumps(owner_label),
            subsystem="topology",
            section="guests",
            subject="passthrough",
            metric="owner",
            object_id=assignment_id,
            display_name=str(raw.get("model") or raw.get("class_name") or assignment_id),
            sort_key=f"720_{index:03d}",
            entity_category="diagnostic",
            icon="mdi:connection",
            extra_attrs={
                "connection": obj + ".connection | default(none)",
                "owner_kind": obj + ".owner_kind | default(none)",
                "owner_id": obj + ".owner_id | default(none)",
                "owner_name": obj + ".owner_name | default(none)",
                "config_key": obj + ".config_key | default(none)",
                "pci_address": obj + ".pci_address | default(none)",
                "pci_class": obj + ".pci_class | default(none)",
                "class_name": obj + ".class_name | default(none)",
                "model": obj + ".model | default(none)",
            },
        )
        components[key] = item

    return payload
