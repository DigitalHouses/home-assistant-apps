"""Pure, read-only Zigbee2MQTT inventory and append-only import.

This module MUST NOT publish MQTT commands or operate relays.
All device settings are sourced from confirmed MQTT state. Area assignment
comes ONLY from an explicit Home Assistant Device/Area Registry lookup.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
from collections.abc import Mapping

_IEEE = re.compile(r"^0x[0-9a-f]{16}$")
_PHYSICAL_SETTINGS = frozenset({
    "operation_mode", "operation_mode_left", "operation_mode_right",
    "operation_mode_center", "power_on_behavior", "power_outage_memory",
    "led_indicator", "led_disabled_night", "indicator_light",
    "click_mode", "mode_switch",
})


class CatalogError(ValueError):
    """Invalid source or user-owned configuration; never silently repair."""


def _ieee(value: object) -> str:
    if not isinstance(value, str) or not _IEEE.fullmatch(value.lower()):
        raise CatalogError("Expected confirmed 16-byte Zigbee IEEE address")
    return value.lower()


def _exposes(raw: object):
    """Flatten Z2M features, including nested switch/light/composite exposes."""
    if not isinstance(raw, list):
        raise CatalogError("Zigbee2MQTT definition.exposes must be a list")
    for item in raw:
        if not isinstance(item, Mapping):
            raise CatalogError("Invalid Zigbee2MQTT exposed feature")
        yield item
        nested = item.get("features")
        if nested is not None:
            yield from _exposes(nested)


def candidate_from_mqtt(
    device: Mapping, *, coordinator_ieee: str, base_topic: str,
    reported_state: Mapping | None,
) -> dict | None:
    """Return confirmed Aqara button/switch candidate, or None for other devices.

    Raises on unconfirmed physical settings. The caller reports this as a scan
    problem instead of importing an unsafe, fabricated Mode Keeper baseline.
    """
    coordinator = _ieee(coordinator_ieee)
    if not isinstance(base_topic, str) or not base_topic or any(
        segment in ("", ".", "..", "+", "#") for segment in base_topic.split("/")
    ):
        raise CatalogError("Invalid Zigbee2MQTT base topic")
    if not isinstance(device, Mapping):
        raise CatalogError("bridge/devices entry must be an object")
    if device.get("type") == "Coordinator":
        return None
    definition = device.get("definition")
    if definition is None:
        return None  # Unsupported / interview not complete.
    if not isinstance(definition, Mapping):
        raise CatalogError("definition must be an object")
    vendor = definition.get("vendor")
    if not isinstance(vendor, str) or vendor.casefold() != "aqara":
        return None
    name = device.get("friendly_name")
    if not isinstance(name, str) or not name or any(
        x in ("", ".", "..", "+", "#", "bridge") for x in name.split("/")
    ):
        raise CatalogError("Invalid Zigbee2MQTT friendly_name")
    model = definition.get("model")
    if not isinstance(model, str) or not model:
        raise CatalogError("Aqara device model is missing")
    ieee = _ieee(device.get("ieee_address"))
    actions: set[str] = set()
    settings: set[str] = set()
    relay_channels: set[str] = set()
    for feature in _exposes(definition.get("exposes")):
        key = feature.get("property", feature.get("name"))
        if not isinstance(key, str):
            continue
        if key == "action" and isinstance(feature.get("values"), list):
            values = feature["values"]
            if any(not isinstance(x, str) or not x for x in values):
                raise CatalogError("Invalid Aqara action values")
            actions.update(values)
        if key in _PHYSICAL_SETTINGS:
            access = feature.get("access")
            if not isinstance(access, int) or access < 0:
                raise CatalogError(f"Invalid access mask for {key}")
            if access & 2:  # Zigbee2MQTT writable setting.
                settings.add(key)
        if feature.get("type") == "switch" or key == "state" or key.startswith("state_"):
            if key == "state" or key.startswith("state_"):
                relay_channels.add(key)
    if not actions:
        return None
    state = reported_state if reported_state is not None else {}
    if not isinstance(state, Mapping):
        raise CatalogError("Device MQTT state must be a JSON object")
    missing = sorted(settings - state.keys())
    if missing:
        raise CatalogError(
            f"{name}: physical settings not confirmed by MQTT: {', '.join(missing)}"
        )
    captured = {key: deepcopy(state[key]) for key in sorted(settings)}
    if any(value is None for value in captured.values()):
        raise CatalogError(f"{name}: physical setting value is null")
    fingerprint = {
        "vendor": "Aqara",
        "model": model,
        "model_id": device.get("model_id"),
        "device_type": device.get("type"),
        "actions": sorted(actions),
        "setting_keys": sorted(settings),
        "relay_channels": sorted(relay_channels),
    }
    return {
        "coordinator_ieee": coordinator,
        "base_topic": base_topic,
        "logical_name": name,
        "ieee": ieee,
        "fingerprint": fingerprint,
        "settings": captured,
    }


def validate_config(raw: object) -> dict:
    """Validate basic logical/physical uniqueness without mutating input."""
    if not isinstance(raw, Mapping) or not isinstance(raw.get("rooms"), list):
        raise CatalogError("Configuration requires rooms list")
    logical: set[tuple[str, str]] = set()
    physical: set[tuple[str, str]] = set()
    for room in raw["rooms"]:
        if not isinstance(room, Mapping) or not isinstance(room.get("switches"), list):
            raise CatalogError("Each room requires switches list")
        area = room.get("area_id")
        if area is not None and (not isinstance(area, str) or not area):
            raise CatalogError("Invalid area_id")
        for switch in room["switches"]:
            if not isinstance(switch, Mapping):
                raise CatalogError("Each switch must be an object")
            network = _ieee(switch.get("coordinator_ieee"))
            ieee = _ieee(switch.get("ieee"))
            name = switch.get("logical_name")
            if not isinstance(name, str) or not name:
                raise CatalogError("Switch logical_name is required")
            key = (network, name)
            hardware = (network, ieee)
            if key in logical or hardware in physical:
                raise CatalogError("Duplicate logical switch or physical IEEE")
            logical.add(key)
            physical.add(hardware)
            if not isinstance(switch.get("fingerprint"), Mapping):
                raise CatalogError("Switch fingerprint is required")
            if not isinstance(switch.get("settings"), Mapping):
                raise CatalogError("Switch captured settings are required")
    return deepcopy(dict(raw))


def import_new(
    config: object,
    candidates: list[dict],
    areas_by_ieee: Mapping[str, dict | None],
) -> tuple[dict, dict]:
    """Append only genuinely new switches; existing switch data is immutable.

    No device is deleted or relocated. Known IEEE renamed in Z2M is an error,
    not a second logical import. New device under an existing logical name is
    reported as skipped; binding must be evaluated separately by Mode Keeper.
    """
    merged = validate_config(config)
    logical = {}
    physical = {}
    for room in merged["rooms"]:
        for entry in room["switches"]:
            logical[(entry["coordinator_ieee"], entry["logical_name"])] = entry
            physical[(entry["coordinator_ieee"], entry["ieee"])] = entry
    report = {"scanned": 0, "added": [], "skipped": [], "problems": []}
    observed: set[tuple[str, str]] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise CatalogError("Candidate must be a validated object")
        coordinator = _ieee(candidate.get("coordinator_ieee"))
        ieee = _ieee(candidate.get("ieee"))
        name = candidate.get("logical_name")
        if not isinstance(name, str) or not name:
            raise CatalogError("Invalid discovered logical name")
        key = (coordinator, name)
        if key in observed:
            raise CatalogError("Duplicate discovered logical name in one network")
        observed.add(key)
        report["scanned"] += 1
        if key in logical:
            report["skipped"].append(name)
            continue
        if (coordinator, ieee) in physical:
            report["problems"].append({
                "name": name, "reason": "known_ieee_renamed",
            })
            continue
        area = areas_by_ieee.get(ieee)
        if area is not None:
            if not isinstance(area, Mapping) or not isinstance(area.get("area_id"), str) or not area["area_id"] or not isinstance(area.get("name"), str) or not area["name"]:
                raise CatalogError(f"Invalid HA Area Registry record for {ieee}")
            area_id = area["area_id"]
            area_name = area["name"]
        else:
            area_id, area_name = None, "Без комнаты"
        room = next((r for r in merged["rooms"] if r["area_id"] == area_id), None)
        if room is None:
            room = {"area_id": area_id, "name": area_name, "switches": []}
            merged["rooms"].append(room)
        item = {
            "coordinator_ieee": coordinator,
            "base_topic": candidate["base_topic"],
            "logical_name": name,
            "ieee": ieee,
            "fingerprint": deepcopy(candidate["fingerprint"]),
            "settings": deepcopy(candidate["settings"]),
            "bindings": {},
            "panel_relay": None,
        }
        room["switches"].append(item)
        logical[key] = item
        physical[(coordinator, ieee)] = item
        report["added"].append({"name": name, "area_id": area_id})
    return merged, report


def resolve_hardware(saved: Mapping, available: list[dict]) -> dict:
    """No write side effects: decide whether a logical device is replaceable."""
    coordinator = _ieee(saved.get("coordinator_ieee"))
    name = saved.get("logical_name")
    peers = [x for x in available if
             x["coordinator_ieee"] == coordinator and x["logical_name"] == name]
    if len(peers) != 1:
        return {"status": "missing" if not peers else "ambiguous"}
    hardware = peers[0]
    if hardware["fingerprint"] != saved.get("fingerprint"):
        return {"status": "incompatible", "observed_ieee": hardware["ieee"]}
    if hardware["ieee"] == saved.get("ieee"):
        return {"status": "same", "observed_ieee": hardware["ieee"]}
    return {"status": "replacement", "observed_ieee": hardware["ieee"]}


def decode_bridge_devices(payload: bytes) -> list[dict]:
    """Decode retained Zigbee2MQTT bridge/devices without silent fallback."""
    try:
        value = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CatalogError("Invalid bridge/devices JSON") from exc
    if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
        raise CatalogError("bridge/devices must be a JSON list of devices")
    return value
