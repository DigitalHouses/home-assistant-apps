"""Read-only HA entity metadata, capabilities and relay protection."""
from .ha_registry import _matched_devices
from .mode_keeper import validate_action_policy
from .catalog import CatalogError
from .light_rules import parse_rule

def safe_switch_targets(registries, config):
    devices, _, entities = registries
    inputs = {sw["ieee"] for room in config["rooms"] for sw in room["switches"]}
    matched = _matched_devices(devices, inputs)
    protected = {d.get("id") for matches in matched.values() for d in matches}
    keys = {sw["entity_id"] for room in config["rooms"] for sw in room["switches"]}
    from collections import Counter
    counts = Counter(e.get("entity_id") for e in entities)
    return {e["entity_id"] for e in entities if e.get("entity_id","").startswith("switch.")
            and counts[e["entity_id"]]==1
            and e.get("disabled_by") is None and e.get("device_id") not in protected
            and e["entity_id"] not in keys}

def target_catalog(registries, states, config):
    devices, areas, entities = registries
    devs = {d["id"]:d for d in devices}
    rooms = {a["area_id"]:a["name"] for a in areas}
    registry = {e["entity_id"]:e for e in entities if e.get("disabled_by") is None}
    switches = safe_switch_targets(registries, config)
    output = {}
    for state in states:
        eid = state.get("entity_id", "")
        if eid not in registry or not (eid.startswith("light.") or eid in switches):
            continue
        e = registry[eid]
        a = state.get("attributes", {})
        modes = set(a.get("supported_color_modes") or [])
        rgb = bool(modes & {"hs", "xy", "rgb", "rgbw", "rgbww"})
        cct = "color_temp" in modes
        brightness = bool(modes - {"onoff", "unknown"})
        route=config.get("light_routes",{}).get(eid,{})
        is_group=route.get("kind")=="group"
        if is_group:
            features=route["features"]
            rgb=bool({"color_xy","color_hs"} & features.keys())
            cct="color_temp" in features
            brightness="brightness" in features
            bounds=features.get("color_temp",{})
            if cct and bounds.get("value_min",0)>0 and bounds.get("value_max",0)>0:
                from math import ceil,floor
                a={**a,"min_color_temp_kelvin":ceil(1_000_000/bounds["value_max"]),
                   "max_color_temp_kelvin":floor(1_000_000/bounds["value_min"])}
        device = devs.get(e.get("device_id"), {})
        area = e.get("area_id") or device.get("area_id")
        output[eid] = {"entity_id":eid,"name":a.get("friendly_name") or e.get("name") or eid,
                       "area":rooms.get(area, "Без комнаты"),"area_id":area,
                       "device_name":device.get("name_by_user") or device.get("name"),
                       "integration":e.get("platform"),"domain":eid.split(".",1)[0],
                       "state":state.get("state"),
                       "brightness":brightness,"rgb":rgb,"cct":cct,"group":is_group,
                       "min_kelvin":a.get("min_color_temp_kelvin"),
                       "max_kelvin":a.get("max_color_temp_kelvin"),
                       "transition":bool(a.get("supported_features",0) & 32) if eid.startswith("light.") else False}
    return output

def supported_actions(sw, policy=None):
    result = []
    keep = {**sw.get("mode_default",{}), **sw.get("keep_mode",{})} if policy is None else policy
    for action in sw["fingerprint"].get("actions", []):
        try:
            validate_action_policy(sw["fingerprint"], keep, action)
            result.append(action)
        except CatalogError:
            continue
    return result

def normalize(rule):
    parsed = parse_rule(rule)
    return [{"entity_id":eid,"operation":parsed.get("target_operations",{}).get(eid,parsed["action"]),
             "data":parsed["target_data"].get(eid, parsed["data"])}
            for eid in parsed["targets"]]

def required_keep(sw, action, existing):
    """Only enable an observed decoupled channel explicitly selected by a user."""
    from itertools import combinations
    possible = {**sw.get("mode_default",{}), **existing}
    extra = [k for k in possible if k not in existing]
    for n in range(len(extra)+1):
        for keys in combinations(extra,n):
            keep = {**existing, **{k:possible[k] for k in keys}}
            try:
                validate_action_policy(sw["fingerprint"],keep,action)
                return keep
            except CatalogError:
                continue
    raise CatalogError("Action requires a confirmed decoupled key")
