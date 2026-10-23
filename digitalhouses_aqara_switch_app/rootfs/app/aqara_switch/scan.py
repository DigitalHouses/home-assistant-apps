"""Manual Zigbee2MQTT Scan/Adopt with stable switch.* configuration keys.

Prefer a uniquely matched, existing HA switch.* entity. Aqara remotes often
have only event/sensor entities: give them a stable logical switch.* key,
without publishing HA Discovery for that key. Hardware is still verified by
coordinator, IEEE and exact Zigbee2MQTT fingerprint.
"""
from __future__ import annotations
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import re

from .catalog import CatalogError, candidate_from_mqtt, decode_bridge_devices, import_new
from .configuration import parse_configuration
from .entity_options import STORE_PATH, parse_rows, store_scan
from .ha_registry import areas_from_registries, switch_entities
from .mode_keeper import capture_keep_mode


def _slug(value: str) -> str:
    """Only ASCII for HA-style keys; never transliterate device names."""
    clean = re.sub(r"[^a-z0-9_]+", "_", value.casefold()).strip("_")
    if not clean:
        clean = "device_" + sha256(value.encode("utf-8")).hexdigest()[:10]
    return clean[:64].rstrip("_")


def _choose_key(candidate: dict, existing: dict, taken: dict,
                preferred: str | None) -> tuple[str, str]:
    """Choose deterministic, distinct logical key without device IEEE.

    Existing key wins for known logical switches (including hardware replace).
    A uniquely matched HA switch may be used as key; otherwise generate one
    from the Z2M friendly name, with stable network-qualified collision fallback.
    """
    owner = (candidate["coordinator_ieee"], candidate["logical_name"])
    remembered = existing.get(owner)
    if remembered is not None:
        return remembered["entity_id"], remembered.get("entity_source", "logical")
    stem = "switch." + _slug(candidate["logical_name"])
    choices = []
    if preferred:
        choices.append((preferred, "ha"))
    choices.append((stem, "logical"))
    net = _slug(candidate["base_topic"].replace("/", "_"))
    choices.append(("switch." + net + "_" + _slug(candidate["logical_name"]), "logical"))
    digest = sha256((":".join(map(str, owner)) + ":" +
                     candidate["base_topic"]).encode("utf-8")).hexdigest()[:12]
    choices.append((stem + "_" + digest, "logical"))
    for key, source in choices:
        if key not in taken or taken[key] == owner:
            return key, source
    raise CatalogError("Cannot allocate unique logical switch key for " + candidate["logical_name"])


def scan_once(snapshots: list[dict], options_client, ha_registry) -> tuple[dict, dict]:
    """Never send a Zigbee /set or trigger light.toggle; Adopt is explicit."""
    if not snapshots:
        raise CatalogError("No verified Zigbee2MQTT networks observed")
    candidates, problems = [], []
    observed_devices = {}
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
                    observed_devices[(item["coordinator_ieee"], item["ieee"])] = (
                        device, states.get(device.get("friendly_name"), {}))
            except (CatalogError, TypeError) as exc:
                problems.append({"name": device.get("friendly_name", "?"),
                                 "reason": str(exc)})
    ha_devices, ha_areas, ha_entities = ha_registry.fetch()
    ieees = {item["ieee"] for item in candidates}
    areas = areas_from_registries(ha_devices, ha_areas, ieees)
    ha_switches, _ = switch_entities(ha_devices, ha_entities, ieees)

    options = options_client.read()
    previous = parse_configuration(options, profile_path=STORE_PATH)
    prior_switches = [s for room in previous["rooms"] for s in room["switches"]]
    by_entity = {sw["entity_id"]: sw for sw in prior_switches}
    by_logical = {(sw["coordinator_ieee"], sw["logical_name"]): sw
                  for sw in prior_switches}
    taken = {sw["entity_id"]: (sw["coordinator_ieee"], sw["logical_name"])
             for sw in prior_switches}
    enriched, logical_only = [], []
    for item in sorted(candidates, key=lambda c: (
            c["coordinator_ieee"], c["base_topic"], c["logical_name"], c["ieee"])):
        owner = (item["coordinator_ieee"], item["logical_name"])
        try:
            key, source = _choose_key(item, by_logical, taken,
                                      ha_switches.get(item["ieee"]))
        except CatalogError as exc:
            problems.append({"name": item["logical_name"], "reason": str(exc)})
            continue
        if key in taken and taken[key] != owner:
            problems.append({"name": item["logical_name"],
                             "reason": "Logical switch key collision: " + key})
            continue
        # A duplicated Z2M identity across snapshots is not a second switch.
        if any(x["entity_id"] == key for x in enriched):
            problems.append({"name": item["logical_name"],
                             "reason": "Duplicate logical switch identity: " + key})
            continue
        taken[key] = owner
        item = {**item, "entity_id": key, "entity_source": source}
        enriched.append(item)
        if source == "logical":
            logical_only.append({"name": item["logical_name"], "key": key})

    replaced, rejected = [], set()
    updated = deepcopy(previous)
    for item in enriched:
        prior = by_entity.get(item["entity_id"])
        if prior is None or prior["ieee"] == item["ieee"]:
            continue
        if (prior["fingerprint"] != item["fingerprint"] or
                prior["logical_name"] != item["logical_name"] or
                prior["coordinator_ieee"] != item["coordinator_ieee"]):
            problems.append({"name": item["logical_name"],
                             "reason": "Replacement fingerprint or logical identity mismatch"})
            rejected.add(item["entity_id"])
            continue
        for room in updated["rooms"]:
            for sw in room["switches"]:
                if sw.get("entity_id") == item["entity_id"]:
                    for k in ("coordinator_ieee", "base_topic", "logical_name",
                              "ieee", "fingerprint", "settings", "entity_source"):
                        sw[k] = deepcopy(item[k])
                    replaced.append(item["entity_id"])

    safe_candidates = [item for item in enriched
                       if item["entity_id"] not in rejected]
    merged, report = import_new(updated, safe_candidates, areas)
    key_by_hardware = {(item["coordinator_ieee"], item["ieee"]): item
                       for item in safe_candidates}
    for room in merged["rooms"]:
        for sw in room["switches"]:
            if not sw.get("entity_id"):
                key = (sw["coordinator_ieee"], sw["ieee"])
                item = key_by_hardware.get(key)
                if item is None:
                    raise CatalogError("Adopted device lacks logical switch key")
                sw["entity_id"] = item["entity_id"]
                sw["entity_source"] = item["entity_source"]
    initialized = []
    for room in merged["rooms"]:
        for sw in room["switches"]:
            if sw.get("mode_policy_initialized", False):
                continue
            observed = observed_devices.get((sw["coordinator_ieee"], sw["ieee"]))
            if observed is None:
                continue
            device, state = observed
            if not isinstance(state, Mapping):
                continue
            keep, warnings = capture_keep_mode(device, state)
            sw["mode_default"] = keep
            sw["mode_policy_initialized"] = True
            initialized.append(sw["entity_id"])
            for warning in warnings:
                problems.append({"name": sw["logical_name"], "reason": warning})
    report["keep_mode_initialized"] = initialized
    report["replaced"] = replaced
    report["logical_only"] = logical_only
    report["problems"].extend(problems)
    report["networks"] = ready
    report["completed_at"] = datetime.now(timezone.utc).isoformat()

    configured = {row["entity_id"] for row in parse_rows(options)}
    absent_rows = any(sw["entity_id"] not in configured
                      for room in merged["rooms"] for sw in room["switches"])
    if report["added"] or replaced or absent_rows or initialized:
        changed = store_scan(merged, options, STORE_PATH)
        options_client.write(changed)
        merged = parse_configuration(options_client.read(), profile_path=STORE_PATH)
    return merged, report
