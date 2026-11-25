"""Cover capability validation and deterministic movement planning."""
from collections.abc import Mapping
import re
from .catalog import CatalogError

SERVICES = {"toggle":"cover.toggle", "open":"cover.open_cover",
            "close":"cover.close_cover", "stop":"cover.stop_cover",
            "position":"cover.set_cover_position"}
FEATURES = {"open":1,"close":2,"position":4,"stop":8}
WINDOW_CLASSES = {"window","door","opening"}
COVER_STATES = {"open","closed","opening","closing"}


def operations(attributes):
    flags = attributes.get("supported_features")
    if type(flags) is not int or flags < 0:
        return []
    result = [op for op,bit in FEATURES.items() if flags & bit]
    if {"open","close"} <= set(result):
        result.insert(0,"toggle")
    return result


def validate_data(operation, data):
    if operation not in SERVICES or not isinstance(data, Mapping):
        raise CatalogError("Unsupported cover operation")
    if set(data) - {"position","window_sensors"}:
        raise CatalogError("Unsupported cover parameter")
    if operation == "position":
        if type(data.get("position")) is not int or not 0 <= data["position"] <= 100:
            raise CatalogError("Cover position must be 0..100")
    elif "position" in data:
        raise CatalogError("Position requires position operation")
    sensors = data.get("window_sensors", [])
    if (not isinstance(sensors,list) or len(sensors)>16 or
            any(not isinstance(e,str) or not re.fullmatch(r"binary_sensor\.[a-z0-9_]+",e) for e in sensors)
            or len(set(sensors)) != len(sensors)):
        raise CatalogError("Invalid window guard sensors")
    return {k:list(v) if k=="window_sensors" else v for k,v in data.items()}


def window_sensor(state):
    return state.get("attributes",{}).get("device_class") in WINDOW_CLASSES


def plan(operation, data, state, guards):
    """Stop is always exempt from the window guard; no delayed replay."""
    data = validate_data(operation,data)
    attrs = state.get("attributes",{})
    current = state.get("state")
    if current not in COVER_STATES:
        raise CatalogError("Cover unavailable or unknown")
    if operation not in operations(attrs):
        raise CatalogError("Cover operation not supported")
    if operation != "stop":
        for eid, sensor in guards.items():
            if not window_sensor(sensor) or sensor.get("state") != "off":
                raise CatalogError("Window guard blocked: " + eid)
    if operation == "toggle":
        if current not in ("open","closed"):
            raise CatalogError("Cover is moving; use Stop")
        operation = "close" if current=="open" else "open"
    desired = {"open":"open","close":"closed","position":"position:"+str(data.get("position")),"stop":None}[operation]
    if operation in ("open","close") and "position" in operations(attrs):
        desired = "position:"+("100" if operation=="open" else "0")
    return operation, {"position":data["position"]} if operation=="position" else {}, desired


def guard_ids(config, entity_id):
    """Union declared guards for this cover, even on disabled/missing keys."""
    from .light_rules import parse_rule
    rules = [rule for room in config["rooms"] for sw in room["switches"]
             for rule in sw.get("configured_bindings",sw.get("bindings",{})).values()]
    rules.extend(parse_rule(rule) for row in config.get("orphan_bindings",[])
                 for rule in row["actions"].values())
    return sorted({sensor for rule in rules
                   for sensor in rule.get("target_data",{}).get(entity_id,{}).get("window_sensors",[])})
