"""Explicit HA REST exception for DigitalHouses' six virtual AQARA LAB lights.

Normal physical Zigbee2MQTT lights must have verified Z2M routes. An absent,
offline or broken Z2M route must NEVER silently fall back to Home Assistant.
Other HA-native lights require positive HA Entity Registry platform verification.
"""
from __future__ import annotations
from collections.abc import Mapping
import json
import re
from .actions import ActionError

LAB_LIGHTS = frozenset({
    "light.dh_aqara_lab_chandelier",
    "light.dh_aqara_lab_spots",
    "light.dh_aqara_lab_sconce",
    "light.dh_aqara_lab_floor_lamp",
    "light.dh_aqara_lab_led_strip",
    "light.dh_aqara_lab_night_light",
})
SHADOW_SECONDS = 5.0
_LIGHT_ID = re.compile(r"^light\.[a-z0-9_]+$")


def authorized_ha_light_ids(entities: object, requested: set[str]) -> set[str]:
    """Only explicitly registered, enabled, non-MQTT HA light entities.

    Never infer HA eligibility from a missing/broken Zigbee2MQTT route.
    Duplicate registry IDs are also rejected rather than guessed.
    """
    if not isinstance(entities, list):
        return set()
    by_id = {}
    duplicates = set()
    for row in entities:
        if not isinstance(row, Mapping):
            continue
        eid = row.get("entity_id")
        if not isinstance(eid, str) or not _LIGHT_ID.fullmatch(eid) or eid not in requested:
            continue
        if eid in by_id:
            duplicates.add(eid)
        by_id[eid] = row
    approved = set()
    for eid, row in by_id.items():
        platform = row.get("platform")
        if (eid not in duplicates and row.get("disabled_by") is None
                and isinstance(platform, str) and re.fullmatch(r"[a-z0-9_]+", platform)
                and platform not in ("mqtt", "zigbee2mqtt")):
            approved.add(eid)
    return approved


def partition_commands(commands: list[dict], z2m_routes: Mapping,
                       ha_approved: set[str] | frozenset[str] = frozenset()
                       ) -> tuple[list[dict], list[dict]]:
    """Split validated commands into Z2M and authorized HA light routes.

    A shared toggle decision is made in the runtime, before either transport
    sends a command. Splitting does not decide independent toggle states.
    """
    mqtt, lab = [], []
    for command in commands:
        z_ids, lab_ids = [], []
        for eid in command["target"]["entity_id"]:
            if eid in z2m_routes:
                z_ids.append(eid)  # Verified Zigbee2MQTT always wins.
            elif eid in LAB_LIGHTS or eid in ha_approved:
                lab_ids.append(eid)
            else:
                z_ids.append(eid)  # Unverified MQTT must fail closed.
        for ids, collection in ((z_ids, mqtt), (lab_ids, lab)):
            if ids:
                copy = {"service":command["service"],"target":{"entity_id":ids}}
                if command.get("data"):
                    copy["data"] = command["data"]
                collection.append(copy)
    return mqtt, lab


def plan_lab(commands: list[dict], read_state, shadows: Mapping,
             now: float, toggle_state_override: str | None = None,
             allowed_lights: set[str] | frozenset[str] = frozenset()
             ) -> tuple[list[dict], list[dict]]:
    """Get authorized HA light states; group-toggle with explicit ON/OFF.

    Offline/unavailable/unknown HA lights are skipped. All commands sent to
    HA are explicit turn_on or turn_off, never light.toggle.
    """
    ready, skipped, seen = [], [], set()
    for command in commands:
        service = command["service"]
        if service not in ("light.toggle","light.turn_on","light.turn_off"):
            raise ActionError("Unsupported LAB light service")
        for eid in command["target"]["entity_id"]:
            if (eid not in LAB_LIGHTS and eid not in allowed_lights) or eid in seen:
                raise ActionError("Unapproved or duplicate HA light")
            seen.add(eid)
            try:
                current = read_state(eid)
            except Exception as exc:
                skipped.append({"light":eid,"reason":"LAB Home Assistant state unavailable"})
                continue
            if current not in ("on", "off"):
                skipped.append({"light":eid,"reason":"LAB light offline or state unknown"})
                continue
            shadow=shadows.get(eid)
            if shadow and now-shadow["at"] <= SHADOW_SECONDS:
                current=shadow["state"]
            ready.append({"light":eid,"service":service,
                          "data":command.get("data",{}),"state":current})
    toggles=[item for item in ready if item["service"] == "light.toggle"]
    group_state=("on" if any(item["state"] == "off" for item in toggles)
                 else "off") if toggles else None
    if toggles and toggle_state_override is not None:
        if toggle_state_override not in ("ON", "OFF"):
            raise ActionError("Invalid synchronized LAB toggle state")
        group_state = toggle_state_override.lower()
    groups = {}
    for item in ready:
        service = ("light.turn_"+group_state if item["service"] == "light.toggle"
                   else item["service"])
        data = item["data"]
        # OFF must not pass ON-only brightness/color settings to Home Assistant.
        if item["service"] == "light.toggle" and service == "light.turn_off":
            data = {k: v for k, v in data.items() if k == "transition"}
        key = (service,json.dumps(data,sort_keys=True))
        if key not in groups:
            groups[key]={"service":service,"target":{"entity_id":[]},"data":data}
        groups[key]["target"]["entity_id"].append(item["light"])
    return list(groups.values()), skipped
