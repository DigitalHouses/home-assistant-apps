from __future__ import annotations

import json
from typing import Any, Mapping

from .config import AppConfig, MqttConfig
from .discovery_groups import route_pve_discovery_groups
from .discovery_guest import build_guest_aware_discovery_payload
from .discovery_metrics import _path, _sensor, _slug
from .discovery_ups import build_ups_discovery_payload
from .discovery_ups_groups import route_ups_discovery_groups
from .identity import HostIdentity
from .topics import build_topics, build_ups_topics
from .ups_control import UpsCapabilities
from .ups_nut import UpsSnapshot
from .ups_shutdown_policy import UpsShutdownPolicy


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def build_shutdown_aware_pve_discovery_payload(
    config: AppConfig,
    identity: HostIdentity,
    *,
    version: str,
    inventory: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    inventory = inventory or {}
    payload = build_guest_aware_discovery_payload(
        config,
        identity,
        version=version,
        inventory=inventory,
    )
    components = payload["components"]
    topics = build_topics(config.mqtt, identity)

    def uid(component: str) -> str:
        return f"{topics.device_id}_{component}"

    previous = _path("host", "shutdown_history", "previous_shutdown")
    history = _path("host", "shutdown_history")

    key, item = _sensor(
        uid=uid,
        state_topic=topics.state,
        app_topic=topics.availability,
        key="previous_shutdown",
        name="Previous shutdown",
        entity_id="sensor.dh_pve_previous_shutdown",
        expression=previous + ".shutdown_class | default('unknown')",
        subsystem="host",
        section="system",
        subject="shutdown",
        metric="previous_shutdown",
        object_id="previous_shutdown",
        display_name="Previous shutdown",
        sort_key="003",
        entity_category="diagnostic",
        icon="mdi:power-cycle",
        extra_attrs={
            "shutdown_reason": previous + ".shutdown_reason | default(none)",
            "shutdown_clean": previous + ".shutdown_clean | default(none)",
            "boot_id": previous + ".boot_id | default(none)",
            "boot_at": previous + ".boot_at | default(none)",
            "shutdown_at": previous + ".shutdown_at | default(none)",
            "uptime_seconds": previous + ".uptime_seconds | default(none)",
            "downtime_seconds": previous + ".downtime_seconds | default(none)",
            "outage_started_at": previous + ".outage_started_at | default(none)",
            "fsd_at": previous + ".fsd_at | default(none)",
            "ups_status_at_fsd": previous + ".ups_status_at_fsd | default(none)",
            "battery_charge_at_fsd": previous + ".battery_charge_at_fsd | default(none)",
            "battery_runtime_at_fsd": previous + ".battery_runtime_at_fsd | default(none)",
            "ups_load_at_fsd": previous + ".ups_load_at_fsd | default(none)",
            "all_guests_stopped_at": previous + ".all_guests_stopped_at | default(none)",
            "guest_shutdown_total_seconds": previous + ".guest_shutdown_total_seconds | default(none)",
            "outage_to_fsd_seconds": previous + ".outage_to_fsd_seconds | default(none)",
            "fsd_to_all_guests_stopped_seconds": previous + ".fsd_to_all_guests_stopped_seconds | default(none)",
            "fsd_to_shutdown_seconds": previous + ".fsd_to_shutdown_seconds | default(none)",
            "all_guests_stopped_to_shutdown_seconds": previous + ".all_guests_stopped_to_shutdown_seconds | default(none)",
            "outage_to_shutdown_seconds": previous + ".outage_to_shutdown_seconds | default(none)",
        },
    )
    components[key] = item

    key, item = _sensor(
        uid=uid,
        state_topic=topics.state,
        app_topic=topics.availability,
        key="shutdown_history",
        name="Shutdown history",
        entity_id="sensor.dh_pve_shutdown_history",
        expression=history + ".history_count | default(0)",
        subsystem="host",
        section="system",
        subject="shutdown",
        metric="history",
        object_id="shutdown_history",
        display_name="Shutdown history",
        sort_key="004",
        entity_category="diagnostic",
        icon="mdi:history",
        extra_attrs={
            "history": history + ".history | default([])",
            "current_boot": history + ".current_boot | default(none)",
        },
    )
    components[key] = item

    guests = _mapping(inventory.get("guests"))
    for plural, kind, label in (("vms", "vm", "VM"), ("lxcs", "lxc", "LXC")):
        records = _mapping(guests.get(plural))
        for index, (guest_id_raw, raw) in enumerate(
            sorted(
                records.items(),
                key=lambda entry: int(str(entry[0])) if str(entry[0]).isdigit() else str(entry[0]),
            ),
            start=1,
        ):
            if not isinstance(raw, Mapping):
                continue
            guest_id = str(guest_id_raw)
            name = str(raw.get("name") or f"{label} {guest_id}")
            current = _path("guests", plural, guest_id)
            previous_guest = _path(
                "host",
                "shutdown_history",
                "previous_shutdown",
                "guests",
                kind,
                guest_id,
            )
            key, item = _sensor(
                uid=uid,
                state_topic=topics.state,
                app_topic=topics.availability,
                key=f"{kind}_{_slug(guest_id)}_shutdown",
                name=f"{label} {guest_id} {name} shutdown",
                entity_id=f"sensor.dh_pve_{kind}_{_slug(guest_id)}_shutdown",
                expression=previous_guest + ".duration_seconds | default(none)",
                subsystem="host",
                section="guests",
                subject=kind,
                metric="shutdown_duration",
                object_id=f"{kind}_{guest_id}",
                display_name=name,
                sort_key=f"710_{0 if kind == 'vm' else 1}_{index:03d}",
                unit="s",
                device_class="duration",
                entity_category="diagnostic",
                icon="mdi:timer-check-outline",
                extra_attrs={
                    "guest_id": json.dumps(guest_id),
                    "guest_kind": json.dumps(kind),
                    "shutdown_timeout_seconds": current + ".shutdown_timeout_seconds | default(none)",
                    "shutdown_order": current + ".shutdown_order | default(none)",
                    "onboot": current + ".onboot | default(false)",
                    "last_shutdown_started_at": previous_guest + ".started_at | default(none)",
                    "last_shutdown_finished_at": previous_guest + ".finished_at | default(none)",
                    "last_shutdown_duration_seconds": previous_guest + ".duration_seconds | default(none)",
                    "last_shutdown_timeout_seconds": previous_guest + ".timeout_seconds | default(none)",
                    "last_shutdown_timeout_ratio": previous_guest + ".timeout_ratio | default(none)",
                    "last_shutdown_result": previous_guest + ".result | default('unknown')",
                    "last_shutdown_forced": previous_guest + ".forced | default(false)",
                },
            )
            components[key] = item

    return route_pve_discovery_groups(payload, topics, inventory=inventory)


def build_shutdown_aware_ups_discovery_payload(
    config: MqttConfig,
    identity: HostIdentity,
    *,
    version: str,
    snapshot: UpsSnapshot | None,
    capabilities: UpsCapabilities | None = None,
    shutdown_policy: UpsShutdownPolicy | None = None,
) -> dict[str, Any]:
    payload = build_ups_discovery_payload(
        config,
        identity,
        version=version,
        snapshot=snapshot,
        capabilities=capabilities,
        shutdown_policy=shutdown_policy,
    )
    topics = build_ups_topics(config, identity)
    pve_topics = build_topics(config, identity)
    components = payload["components"]
    availability = [
        {
            "topic": pve_topics.availability,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
    ]

    components["guest_shutdown_budget"] = {
        "platform": "sensor",
        "name": "Guest shutdown budget",
        "unique_id": f"{topics.device_id}_guest_shutdown_budget",
        "default_entity_id": "sensor.dh_pve_ups_guest_shutdown_budget",
        "state_topic": topics.state,
        "value_template": "{{ value_json.shutdown_policy.guest_shutdown_budget_seconds | default(none) }}",
        "unit_of_measurement": "s",
        "device_class": "duration",
        "entity_category": "diagnostic",
        "availability": availability,
        "availability_mode": "all",
        "icon": "mdi:timer-sand",
    }
    components["shutdown_readiness"] = {
        "platform": "sensor",
        "name": "Shutdown readiness",
        "unique_id": f"{topics.device_id}_shutdown_readiness",
        "default_entity_id": "sensor.dh_pve_ups_shutdown_readiness",
        "state_topic": topics.state,
        "value_template": "{{ value_json.shutdown_readiness.status | default('skip') }}",
        "entity_category": "diagnostic",
        "availability": availability,
        "availability_mode": "all",
        "icon": "mdi:shield-check-outline",
        "json_attributes_topic": topics.state,
        "json_attributes_template": (
            "{{ {'issues': value_json.shutdown_readiness.issues | default([]), "
            "'guest_shutdown_budget_seconds': value_json.shutdown_readiness.guest_shutdown_budget_seconds | default(none), "
            "'history_available': value_json.shutdown_readiness.history_available | default(false)} | tojson }}"
        ),
    }
    return route_ups_discovery_groups(payload, topics)
