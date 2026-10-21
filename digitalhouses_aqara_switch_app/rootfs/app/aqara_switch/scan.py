"""Explicit clean Scan/Adopt: no migration or invented HA entities."""
from __future__ import annotations
from collections.abc import Mapping
from datetime import datetime, timezone
from copy import deepcopy

from .catalog import CatalogError, candidate_from_mqtt, decode_bridge_devices, import_new
from .configuration import parse_configuration
from .entity_options import STORE_PATH, store_scan
from .ha_registry import areas_from_registries, switch_entities


def scan_once(snapshots: list[dict], options_client, ha_registry) -> tuple[dict, dict]:
    if not snapshots:
        raise CatalogError("No verified Zigbee2MQTT networks observed")
    candidates, problems = [], []
    ready = 0
    for snapshot in snapshots:
        if not isinstance(snapshot, Mapping):
            raise CatalogError("Invalid Zigbee2MQTT scan snapshot")
        base, coordinator, raw = (
            snapshot.get("base_topic"), snapshot.get("coordinator_ieee"),
            snapshot.get("devices"))
        if not isinstance(raw, bytes) or not isinstance(base, str):
            raise CatalogError("Incomplete Zigbee2MQTT inventory")
        devices = decode_bridge_devices(raw)
        states = snapshot.get("states")
        if not isinstance(states, Mapping):
            raise CatalogError("Invalid Zigbee2MQTT state snapshot")
        ready += 1
        for device in devices:
            try:
                item = candidate_from_mqtt(
                    device, coordinator_ieee=coordinator, base_topic=base,
                    reported_state=states.get(device.get("friendly_name")))
                if item is not None:
                    candidates.append(item)
            except (CatalogError, TypeError) as exc:
                problems.append({"name": device.get("friendly_name", "?"),
                                 "reason": str(exc)})
    ha_devices, ha_areas, ha_entities = ha_registry.fetch()
    ieees = {item["ieee"] for item in candidates}
    areas = areas_from_registries(ha_devices, ha_areas, ieees)
    identities, errors = switch_entities(ha_devices, ha_entities, ieees)
    candidates = [dict(item, entity_id=identities[item["ieee"]])
                  for item in candidates if item["ieee"] in identities]
    for ieee, reason in errors.items():
        name = next((x["logical_name"] for x in candidates if x["ieee"] == ieee), ieee)
        problems.append({"name": name, "reason": reason})

    options = options_client.read()
    previous = parse_configuration(options)
    # Preserve the logical HA entity across a physical replacement when
    # the actual HA registry still points to that same entity_id.
    replaced = []
    by_entity = {s.get("entity_id"): s
                 for room in previous["rooms"] for s in room["switches"]}
    updated = deepcopy(previous)
    for candidate in candidates:
        prior = by_entity.get(candidate["entity_id"])
        if prior is None or prior["ieee"] == candidate["ieee"]:
            continue
        if prior["fingerprint"] != candidate["fingerprint"]:
            problems.append({"name": candidate["logical_name"],
                             "reason": "Replacement fingerprint mismatch"})
            continue
        for room in updated["rooms"]:
            for sw in room["switches"]:
                if sw.get("entity_id") == candidate["entity_id"]:
                    for key in ("coordinator_ieee", "base_topic", "logical_name",
                                "ieee", "fingerprint", "settings"):
                        sw[key] = deepcopy(candidate[key])
                    replaced.append(candidate["entity_id"])

    # Only candidates without unsafe conflicts may reach the append-only import.
    safe_candidates = [
        item for item in candidates if
        (by_entity.get(item["entity_id"]) is None or
         by_entity[item["entity_id"]]["ieee"] == item["ieee"] or
         item["entity_id"] in replaced)
    ]
    merged, report = import_new(updated, safe_candidates, areas)
    ieee_to_entity = {c["ieee"]: c["entity_id"] for c in safe_candidates}
    for room in merged["rooms"]:
        for sw in room["switches"]:
            if not sw.get("entity_id"):
                sw["entity_id"] = ieee_to_entity.get(sw["ieee"])
                if not sw["entity_id"]:
                    raise CatalogError("Adopted device lacks confirmed HA entity_id")

    report["replaced"] = replaced
    report["problems"].extend(problems)
    report["networks"] = ready
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    if report["added"] or replaced:
        changed = store_scan(merged, options, STORE_PATH)
        options_client.write(changed)
        merged = parse_configuration(options_client.read())
    return merged, report
