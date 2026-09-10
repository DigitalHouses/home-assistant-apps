from __future__ import annotations

import json
import re
from typing import Any, Mapping

from .config import AppConfig
from .discovery import build_discovery_payload
from .identity import HostIdentity
from .topics import build_topics


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return re.sub(r"_+", "_", value) or "unknown"


def _path(subsystem: str, *parts: str) -> str:
    value = f"value_json.subsystems.{subsystem}.data"
    for part in parts:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part):
            value += f".{part}"
        else:
            value += f"[{json.dumps(part)}]"
    return value


def _availability(state_topic: str, app_topic: str, subsystem: str) -> list[dict[str, str]]:
    return [
        {
            "topic": app_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
        },
        {
            "topic": state_topic,
            "value_template": (
                "{{ 'online' if value_json.subsystems."
                + subsystem
                + ".available | default(false) else 'offline' }}"
            ),
            "payload_available": "online",
            "payload_not_available": "offline",
        },
    ]


def _object_availability(state_topic: str, expression: str) -> dict[str, str]:
    return {
        "topic": state_topic,
        "value_template": "{{ 'online' if " + expression + " | default(false) else 'offline' }}",
        "payload_available": "online",
        "payload_not_available": "offline",
    }


def _attrs(
    section: str,
    subject: str,
    metric: str,
    object_id: str,
    display_name: str,
    sort_key: str,
    extra: Mapping[str, str] | None = None,
) -> str:
    fields = [
        "'proxmox_integration':'dh_pve_app'",
        f"'proxmox_section':{json.dumps(section)}",
        f"'proxmox_subject':{json.dumps(subject)}",
        f"'proxmox_metric':{json.dumps(metric)}",
        f"'proxmox_object_id':{json.dumps(object_id)}",
        f"'proxmox_display_name':{json.dumps(display_name)}",
        f"'proxmox_sort_key':{json.dumps(sort_key)}",
    ]
    for key, value in (extra or {}).items():
        fields.append(f"{json.dumps(key)}:{value}")
    return "{{ {" + ",".join(fields) + "} | tojson }}"


def _sensor(
    *, uid, state_topic: str, app_topic: str, key: str, name: str,
    entity_id: str, expression: str, subsystem: str, section: str,
    subject: str, metric: str, object_id: str, display_name: str,
    sort_key: str, unit: str | None = None, device_class: str | None = None,
    state_class: str | None = None, entity_category: str | None = None,
    icon: str | None = None, extra_attrs: Mapping[str, str] | None = None,
    object_availability: str | None = None,
) -> tuple[str, dict[str, Any]]:
    item: dict[str, Any] = {
        "platform": "sensor", "name": name, "unique_id": uid(key),
        "default_entity_id": entity_id, "state_topic": state_topic,
        "value_template": "{{ " + expression + " }}",
        "availability": _availability(state_topic, app_topic, subsystem),
        "availability_mode": "all", "json_attributes_topic": state_topic,
        "json_attributes_template": _attrs(
            section, subject, metric, object_id, display_name, sort_key, extra_attrs
        ),
    }
    if object_availability:
        item["availability"].append(_object_availability(state_topic, object_availability))
    if unit:
        item["unit_of_measurement"] = unit
    if device_class:
        item["device_class"] = device_class
    if state_class:
        item["state_class"] = state_class
    if entity_category:
        item["entity_category"] = entity_category
    if icon:
        item["icon"] = icon
    return key, item


def _binary(
    *, uid, state_topic: str, app_topic: str, key: str, name: str,
    entity_id: str, expression: str, subsystem: str | None, section: str,
    subject: str, metric: str, object_id: str, display_name: str,
    sort_key: str, device_class: str | None = None,
    entity_category: str | None = None, icon: str | None = None,
    extra_attrs: Mapping[str, str] | None = None,
    object_availability: str | None = None,
) -> tuple[str, dict[str, Any]]:
    availability = [{
        "topic": app_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
    }]
    if subsystem:
        availability += _availability(state_topic, app_topic, subsystem)[1:]
    item: dict[str, Any] = {
        "platform": "binary_sensor", "name": name, "unique_id": uid(key),
        "default_entity_id": entity_id, "state_topic": state_topic,
        "value_template": "{{ " + expression + " }}",
        "payload_on": "ON", "payload_off": "OFF",
        "availability": availability, "availability_mode": "all",
        "json_attributes_topic": state_topic,
        "json_attributes_template": _attrs(
            section, subject, metric, object_id, display_name, sort_key, extra_attrs
        ),
    }
    if object_availability:
        item["availability"].append(_object_availability(state_topic, object_availability))
    if device_class:
        item["device_class"] = device_class
    if entity_category:
        item["entity_category"] = entity_category
    if icon:
        item["icon"] = icon
    return key, item


def build_full_discovery_payload(
    config: AppConfig,
    identity: HostIdentity,
    *,
    version: str,
    inventory: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    payload = build_discovery_payload(config, identity, version=version)
    topics = build_topics(config.mqtt, identity)
    components = payload["components"]
    inventory = inventory or {}

    def uid(component: str) -> str:
        return f"{topics.device_id}_{component}"

    static = [
        _sensor(
            uid=uid, state_topic=topics.state, app_topic=topics.availability,
            key="system", name="System", entity_id="sensor.dh_pve_system",
            expression=_path("host", "hostname") + " | default('unknown')",
            subsystem="host", section="system", subject="host", metric="identity",
            object_id=identity.instance_id, display_name=identity.node_name, sort_key="001",
            entity_category="diagnostic", icon="mdi:server",
            extra_attrs={
                "manufacturer": _path("host", "manufacturer") + " | default(none)",
                "model": _path("host", "model") + " | default(none)",
                "board_vendor": _path("host", "board_vendor") + " | default(none)",
                "board_model": _path("host", "board_model") + " | default(none)",
                "kernel_version": _path("host", "kernel_version") + " | default(none)",
                "proxmox_version": _path("host", "proxmox_version") + " | default(none)",
                "primary_ip": _path("host", "primary_ip") + " | default(none)",
                "cpu_model": _path("host", "cpu", "model") + " | default(none)",
                "cpu_cores": _path("host", "cpu", "cores") + " | default(none)",
                "cpu_threads": _path("host", "cpu", "threads") + " | default(none)",
                "memory_type": _path("host", "memory_inventory", "memory_type") + " | default(none)",
                "memory_form_factor": _path("host", "memory_inventory", "form_factor") + " | default(none)",
                "memory_slots_populated": _path("host", "memory_inventory", "populated_slots") + " | default(none)",
                "memory_slots_total": _path("host", "memory_inventory", "total_slots") + " | default(none)",
                "memory_speed_mt_s": _path("host", "memory_inventory", "configured_speed_mt_s") + " | default(none)",
            },
        ),
        _sensor(
            uid=uid, state_topic=topics.state, app_topic=topics.availability,
            key="last_boot", name="Last boot", entity_id="sensor.dh_pve_last_boot",
            expression=_path("host", "boot_time") + " | default(none)",
            subsystem="host", section="system", subject="host", metric="last_boot",
            object_id=identity.instance_id, display_name=identity.node_name, sort_key="002",
            device_class="timestamp", entity_category="diagnostic", icon="mdi:restart",
        ),
        _sensor(
            uid=uid, state_topic=topics.state, app_topic=topics.availability,
            key="cpu_usage", name="CPU usage", entity_id="sensor.dh_pve_cpu_usage",
            expression=_path("cpu", "usage_percent") + " | default(none)",
            subsystem="cpu", section="cpu", subject="cpu", metric="usage",
            object_id="cpu", display_name="CPU", sort_key="100",
            unit="%", state_class="measurement", icon="mdi:cpu-64-bit",
        ),
        _sensor(
            uid=uid, state_topic=topics.state, app_topic=topics.availability,
            key="cpu_temperature", name="CPU temperature", entity_id="sensor.dh_pve_cpu_temperature",
            expression=_path("cpu", "temperature_c") + " | default(none)",
            subsystem="cpu", section="cpu", subject="cpu", metric="temperature",
            object_id="cpu", display_name="CPU", sort_key="110",
            unit="°C", device_class="temperature", state_class="measurement", icon="mdi:thermometer",
        ),
        _sensor(
            uid=uid, state_topic=topics.state, app_topic=topics.availability,
            key="cpu_frequency", name="CPU frequency", entity_id="sensor.dh_pve_cpu_frequency",
            expression=_path("cpu", "frequency", "average_mhz") + " | default(none)",
            subsystem="cpu", section="cpu", subject="cpu", metric="frequency",
            object_id="cpu", display_name="CPU", sort_key="120",
            unit="MHz", state_class="measurement", icon="mdi:speedometer",
        ),
        _binary(
            uid=uid, state_topic=topics.state, app_topic=topics.availability,
            key="cpu_throttling", name="CPU throttling",
            entity_id="binary_sensor.dh_pve_cpu_throttling",
            expression="'ON' if " + _path("cpu", "throttling_active") + " | default(false) else 'OFF'",
            subsystem="cpu", section="cpu", subject="cpu", metric="throttling",
            object_id="cpu", display_name="CPU", sort_key="130",
            device_class="problem", entity_category="diagnostic", icon="mdi:speedometer-slow",
        ),
        _sensor(
            uid=uid, state_topic=topics.state, app_topic=topics.availability,
            key="memory_usage", name="Memory usage", entity_id="sensor.dh_pve_memory_usage",
            expression=_path("memory", "usage_percent") + " | default(none)",
            subsystem="memory", section="memory", subject="memory", metric="usage",
            object_id="memory", display_name="RAM", sort_key="200",
            unit="%", state_class="measurement", icon="mdi:memory",
            extra_attrs={
                "used_gib": _path("memory", "used_gib") + " | default(none)",
                "total_gib": _path("memory", "total_gib") + " | default(none)",
            },
        ),
        _sensor(
            uid=uid, state_topic=topics.state, app_topic=topics.availability,
            key="swap_usage", name="Swap usage", entity_id="sensor.dh_pve_swap_usage",
            expression=_path("memory", "swap_usage_percent") + " | default(none)",
            subsystem="memory", section="memory", subject="swap", metric="usage",
            object_id="swap", display_name="Swap", sort_key="210",
            unit="%", state_class="measurement", entity_category="diagnostic",
            icon="mdi:swap-horizontal",
        ),
    ]
    for key, item in static:
        components[key] = item

    for subsystem in ("host", "cpu", "memory", "storage", "smart", "gpu", "fans"):
        key, item = _binary(
            uid=uid, state_topic=topics.state, app_topic=topics.availability,
            key=f"collector_{subsystem}", name=f"{subsystem.title()} collector",
            entity_id=f"binary_sensor.dh_pve_{subsystem}_collector",
            expression="'ON' if value_json.subsystems." + subsystem + ".available | default(false) else 'OFF'",
            subsystem=None, section="diagnostic", subject="collector", metric="availability",
            object_id=subsystem, display_name=subsystem, sort_key=f"900_{subsystem}",
            device_class="connectivity", entity_category="diagnostic",
        )
        components[key] = item

    storages = inventory.get("storage")
    if isinstance(storages, Mapping):
        for index, (name, raw) in enumerate(sorted(storages.items()), start=1):
            if not isinstance(raw, Mapping):
                continue
            name = str(name)
            slug = _slug(name)
            obj = _path("storage", name)
            key, item = _sensor(
                uid=uid, state_topic=topics.state, app_topic=topics.availability,
                key=f"storage_{slug}_usage", name=f"Storage {name} usage",
                entity_id=f"sensor.dh_pve_storage_{slug}_usage",
                expression=obj + ".usage_percent | default(none)",
                subsystem="storage", section="storage", subject="storage", metric="usage",
                object_id=name, display_name=name, sort_key=f"300_{index:03d}",
                unit="%", state_class="measurement", icon="mdi:database",
                extra_attrs={
                    "storage_type": obj + ".storage_type | default(none)",
                    "status": obj + ".status | default(none)",
                    "used_gib": obj + ".used_gib | default(none)",
                    "total_gib": obj + ".total_gib | default(none)",
                },
            )
            components[key] = item

    disks = inventory.get("smart")
    if isinstance(disks, Mapping):
        for index, (disk_id, raw) in enumerate(sorted(disks.items()), start=1):
            if not isinstance(raw, Mapping):
                continue
            disk_id = str(disk_id)
            slug = _slug(disk_id)
            obj = _path("smart", disk_id)
            display = str(raw.get("model") or disk_id)
            object_online = obj + ".available"
            ident = {
                "model": obj + ".model | default(none)",
                "serial": obj + ".serial | default(none)",
                "disk_type": obj + ".disk_type | default(none)",
                "device_path": obj + ".device_path | default(none)",
            }
            key, item = _sensor(
                uid=uid, state_topic=topics.state, app_topic=topics.availability,
                key=f"disk_{slug}_health", name=f"Disk health - {display}",
                entity_id=f"sensor.dh_pve_disk_{slug}_health",
                expression=obj + ".health_state | default('UNKNOWN')",
                subsystem="smart", section="disk", subject="disk", metric="health",
                object_id=disk_id, display_name=display, sort_key=f"400_{index:03d}_00",
                icon="mdi:harddisk", object_availability=object_online,
                extra_attrs={
                    **ident,
                    "recommendation": obj + ".recommendation | default(none)",
                    "health_reasons": obj + ".health_reasons | default([])",
                },
            )
            components[key] = item
            key, item = _binary(
                uid=uid, state_topic=topics.state, app_topic=topics.availability,
                key=f"disk_{slug}_smart_problem", name=f"SMART problem - {display}",
                entity_id=f"binary_sensor.dh_pve_disk_{slug}_smart_problem",
                expression="'ON' if " + obj + ".smart_passed is sameas false else 'OFF'",
                subsystem="smart", section="disk", subject="disk", metric="smart_problem",
                object_id=disk_id, display_name=display, sort_key=f"400_{index:03d}_01",
                device_class="problem", entity_category="diagnostic",
                icon="mdi:harddisk-alert", extra_attrs=ident,
                object_availability=object_online,
            )
            components[key] = item

            fields = (
                ("temperature_c", "temperature", "temperature", "°C", "temperature", "measurement"),
                ("wear_used_percent", "wear", "wear", "%", None, "measurement"),
                ("power_on_hours", "power_on_hours", "power_on_hours", "h", "duration", "total_increasing"),
                ("media_errors", "media_errors", "media_errors", None, None, "total_increasing"),
                ("reallocated_sectors", "reallocated", "reallocated_sectors", None, None, "total_increasing"),
                ("pending_sectors", "pending", "pending_sectors", None, None, "measurement"),
                ("offline_uncorrectable", "uncorrectable", "offline_uncorrectable", None, None, "total_increasing"),
                ("unsafe_shutdowns", "unsafe_shutdowns", "unsafe_shutdowns", None, None, "total_increasing"),
                ("data_written_tb", "data_written", "data_written", "TB", "data_size", "total_increasing"),
            )
            for offset, (field, suffix, metric, unit, device_class, state_class) in enumerate(fields, start=2):
                if raw.get(field) is None:
                    continue
                key, item = _sensor(
                    uid=uid, state_topic=topics.state, app_topic=topics.availability,
                    key=f"disk_{slug}_{suffix}",
                    name=f"Disk {suffix.replace('_', ' ')} - {display}",
                    entity_id=f"sensor.dh_pve_disk_{slug}_{suffix}",
                    expression=obj + f".{field} | default(none)",
                    subsystem="smart", section="disk", subject="disk", metric=metric,
                    object_id=disk_id, display_name=display, sort_key=f"400_{index:03d}_{offset:02d}",
                    unit=unit, device_class=device_class, state_class=state_class,
                    entity_category="diagnostic" if field not in {"temperature_c", "wear_used_percent"} else None,
                    icon="mdi:harddisk", extra_attrs=ident,
                    object_availability=object_online,
                )
                components[key] = item

            daily = raw.get("daily")
            if isinstance(daily, Mapping) and daily.get("max_temperature_c") is not None:
                key, item = _sensor(
                    uid=uid, state_topic=topics.state, app_topic=topics.availability,
                    key=f"disk_{slug}_daily_max_temperature",
                    name=f"Disk daily max temperature - {display}",
                    entity_id=f"sensor.dh_pve_disk_{slug}_daily_max_temperature",
                    expression=obj + ".daily.max_temperature_c | default(none)",
                    subsystem="smart", section="disk", subject="disk", metric="daily_max_temperature",
                    object_id=disk_id, display_name=display, sort_key=f"400_{index:03d}_20",
                    unit="°C", device_class="temperature", state_class="measurement",
                    entity_category="diagnostic", icon="mdi:thermometer-chevron-up",
                    extra_attrs=ident, object_availability=object_online,
                )
                components[key] = item

    gpus = inventory.get("gpu")
    if isinstance(gpus, Mapping):
        for index, (gpu_id, raw) in enumerate(sorted(gpus.items()), start=1):
            if not isinstance(raw, Mapping):
                continue
            gpu_id = str(gpu_id)
            slug = _slug(gpu_id)
            obj = _path("gpu", gpu_id)
            display = str(raw.get("display_name") or raw.get("model") or gpu_id)
            attrs = {
                "model": obj + ".model | default(none)",
                "pci_address": obj + ".pci_address | default(none)",
                "kernel_driver": obj + ".kernel_driver | default(none)",
                "connection": obj + ".connection | default(none)",
                "source_type": obj + ".source_type | default(none)",
                "source_id": obj + ".source_id | default(none)",
                "source_name": obj + ".source_name | default(none)",
            }
            key, item = _sensor(
                uid=uid, state_topic=topics.state, app_topic=topics.availability,
                key=f"gpu_{slug}_owner", name=f"GPU owner - {display}",
                entity_id=f"sensor.dh_pve_gpu_{slug}_owner",
                expression=obj + ".owner | default('unknown')",
                subsystem="gpu", section="graphics", subject="gpu", metric="owner",
                object_id=gpu_id, display_name=display, sort_key=f"500_{index:03d}_00",
                entity_category="diagnostic", icon="mdi:expansion-card", extra_attrs=attrs,
            )
            components[key] = item
            if raw.get("temperature_c") is not None:
                key, item = _sensor(
                    uid=uid, state_topic=topics.state, app_topic=topics.availability,
                    key=f"gpu_{slug}_temperature", name=f"GPU temperature - {display}",
                    entity_id=f"sensor.dh_pve_gpu_{slug}_temperature",
                    expression=obj + ".temperature_c | default(none)",
                    subsystem="gpu", section="graphics", subject="gpu", metric="temperature",
                    object_id=gpu_id, display_name=display, sort_key=f"500_{index:03d}_01",
                    unit="°C", device_class="temperature", state_class="measurement",
                    icon="mdi:thermometer", extra_attrs=attrs,
                )
                components[key] = item
            if str(raw.get("vendor_id", "")).lower() == "0x8086":
                key, item = _sensor(
                    uid=uid, state_topic=topics.state, app_topic=topics.availability,
                    key=f"gpu_{slug}_transcoding", name=f"GPU transcoding - {display}",
                    entity_id=f"sensor.dh_pve_gpu_{slug}_transcoding",
                    expression=obj + ".transcoding_load_percent | default(none)",
                    subsystem="gpu", section="graphics", subject="gpu", metric="transcoding",
                    object_id=gpu_id, display_name=display, sort_key=f"500_{index:03d}_02",
                    unit="%", state_class="measurement", entity_category="diagnostic",
                    icon="mdi:video", extra_attrs=attrs,
                )
                components[key] = item

    fans = inventory.get("fans")
    if isinstance(fans, Mapping):
        for index, (fan_id, raw) in enumerate(sorted(fans.items()), start=1):
            if not isinstance(raw, Mapping):
                continue
            fan_id = str(fan_id)
            slug = _slug(fan_id)
            obj = _path("fans", fan_id)
            display = str(raw.get("display_name") or raw.get("label") or fan_id)
            key, item = _sensor(
                uid=uid, state_topic=topics.state, app_topic=topics.availability,
                key=f"fan_{slug}_rpm", name=display,
                entity_id=f"sensor.dh_pve_fan_{slug}_rpm",
                expression=obj + ".rpm | default(none)",
                subsystem="fans", section="cooling", subject="fan", metric="rpm",
                object_id=fan_id, display_name=display, sort_key=f"600_{index:03d}",
                unit="rpm", state_class="measurement", entity_category="diagnostic",
                icon="mdi:fan",
                extra_attrs={
                    "chip": obj + ".chip | default(none)",
                    "label": obj + ".label | default(none)",
                },
            )
            components[key] = item

    return payload
