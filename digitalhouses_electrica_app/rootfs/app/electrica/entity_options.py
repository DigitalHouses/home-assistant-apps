"""Compact YAML switch.* logical keys -> Aqara actions -> light targets.

No migration. The switch.* key may name an existing HA switch entity or be
logical-only for battery remotes. Never register a fake HA entity.
"""
from __future__ import annotations
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
import re
import yaml

from .catalog import CatalogError, validate_config
from .light_rules import parse_rule
from . import sensor_rules, schedule_rules
from .mode_keeper import global_policy, validate_keep_mode, validate_action_policy, POLICIES, PHYSICAL, action_channels, MODE_TO_RELAY
from .structured_options import _read_profiles, _save_profiles

STORE_PATH = Path("/data/adopted_switches.json")
_ENTITY = re.compile(r"^switch\.[a-z0-9_]+$")
_LIGHT = re.compile(r"^light\.[a-z0-9_]+$")


def parse_rows(options: Mapping) -> list[dict]:
    global_policy(options)  # validate runtime options even on empty install
    raw = options.get("switches")
    if not isinstance(raw, str):
        raise CatalogError("switches must be a YAML text field")
    try:
        rows = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise CatalogError("Invalid switches YAML") from exc
    if not isinstance(rows, list):
        raise CatalogError("switches YAML must be a list")
    flat = []
    for row in rows:
        if not isinstance(row, Mapping) or len(row) != 1:
            raise CatalogError("Each switch row must have exactly one entity_id key")
        entity_id, value = next(iter(row.items()))
        if not isinstance(value, Mapping) or "entity_id" in value:
            raise CatalogError("Invalid switch row")
        flat.append(dict(value, entity_id=entity_id))
    return validate_rows(flat)


def validate_rows(rows: object) -> list[dict]:
    """Validate the authoritative JSON rows without YAML conversion.

    Keep the original action representation and every supported field, so an
    Aqara v0.2.3 export can be imported and exported without losing settings.
    """
    if not isinstance(rows, list):
        raise CatalogError("Binding rows must be a list")
    result, unique = [], set()
    for row in rows:
        if not isinstance(row, Mapping) or "entity_id" not in row:
            raise CatalogError("Binding row requires entity_id")
        entity_id = row["entity_id"]
        value = {key: val for key, val in row.items() if key != "entity_id"}
        if schedule_rules.is_schedule(entity_id):
            if entity_id in unique:raise CatalogError("Duplicate schedule ID")
            unique.add(entity_id)
            result.append(schedule_rules.validate_row(dict(row)))
            continue
        if sensor_rules.is_source(entity_id):
            if entity_id in unique:raise CatalogError("Duplicate sensor entity_id")
            unique.add(entity_id)
            result.append(sensor_rules.validate_row(row))
            continue
        if not isinstance(entity_id, str) or not _ENTITY.fullmatch(entity_id):
            raise CatalogError("Switch key must be switch.* (HA entity or logical config key)")
        if entity_id in unique:
            raise CatalogError("Duplicate logical switch entity_id")
        unique.add(entity_id)
        if (not isinstance(value, Mapping) or
                not {"enabled", "actions"} <= set(value) or
                set(value) - {"enabled", "actions", "keep_mode", "maintenance_mode", "disabled_actions", "relay_timers"}):
            raise CatalogError("Switch requires enabled and actions, optionally keep_mode/maintenance_mode")
        if "maintenance_mode" in value and type(value["maintenance_mode"]) is not bool:
            raise CatalogError("Local maintenance_mode must be boolean")
        keep = value.get("keep_mode", {})
        if not isinstance(keep, Mapping):
            raise CatalogError("keep_mode must be a mapping")
        for key, desired in keep.items():
            if key not in ("left", "right", "center", "main") or desired not in POLICIES:
                raise CatalogError("keep_mode requires a supported key policy and channel")
        if not isinstance(value["enabled"], bool) or not isinstance(value["actions"], Mapping):
            raise CatalogError("enabled must be boolean, actions must be mapping")
        actions = {}
        for press, rule in value["actions"].items():
            if not isinstance(press, str) or not press:
                raise CatalogError("Invalid action name")
            # A declared physical channel must never retain an assignment.
            # Ambiguous unsuffixed events are checked against hardware in project.
            explicit_channels = action_channels(press, ())
            if any(keep.get(k) == PHYSICAL for k in explicit_channels) or (
                    not explicit_channels and set(keep) == {"main"} and keep["main"] == PHYSICAL):
                raise CatalogError("Physical key cannot have Actions: " + press)
            parse_rule(rule)  # fail closed before persisting user configuration
            actions[press] = deepcopy(rule)
        item = {"entity_id": entity_id, "enabled": value["enabled"], "actions": actions}
        if "maintenance_mode" in value:
            item["maintenance_mode"] = value["maintenance_mode"]
        if "keep_mode" in value:
            item["keep_mode"] = dict(keep)
        if "relay_timers" in value:
            timers=value["relay_timers"]
            if not isinstance(timers,Mapping) or any(keep.get(k)!=PHYSICAL or type(v) is not int or not 1<=v<=86400 for k,v in timers.items()):
                raise CatalogError("Relay timer requires explicit physical key and 1..86400 seconds")
            item["relay_timers"]=dict(timers)
        if "disabled_actions" in value:
            disabled = value["disabled_actions"]
            if (not isinstance(disabled, list) or any(not isinstance(a,str) or a not in actions for a in disabled)
                    or len(disabled) != len(set(disabled))):
                raise CatalogError("Invalid disabled_actions")
            item["disabled_actions"] = list(disabled)
        result.append(item)
    return result


def render_rows(rows: list[dict]) -> str:
    return yaml.safe_dump([
        {row["entity_id"]: {key: row[key] for key in ("enabled", "maintenance_mode", "keep_mode", "actions", "disabled_actions", "assignments", "lux_entity_id", "lux_threshold", "relay_timers", "name", "trigger") if key in row}}
        for row in rows], allow_unicode=True, sort_keys=False,
        default_flow_style=False)


def project(profiles: Mapping, options: Mapping) -> dict:
    data = validate_config(profiles)
    rows = parse_rows(options)
    sensors={r["entity_id"]:r for r in rows if sensor_rules.is_source(r["entity_id"])}
    if sensors:data["sensor_bindings"]=sensors
    else:data.pop("sensor_bindings",None)
    schedules={r["entity_id"]:r for r in rows if schedule_rules.is_schedule(r["entity_id"])}
    if schedules:data["schedules"]=schedules
    else:data.pop("schedules",None)
    rows=[r for r in rows if not sensor_rules.is_source(r["entity_id"]) and not schedule_rules.is_schedule(r["entity_id"])]
    index = {}
    for room in data["rooms"]:
        for item in room["switches"]:
            entity_id = item.get("entity_id")
            if not isinstance(entity_id, str) or not _ENTITY.fullmatch(entity_id):
                raise CatalogError("Adopted hardware lacks a unique logical switch key")
            if entity_id in index:
                raise CatalogError("Duplicate adopted logical switch key")
            index[entity_id] = item
            item["bindings"] = {}
            item.pop("configured_bindings", None)
            item.pop("disabled_actions", None)
            item["enabled"] = False
            item["maintenance_mode"] = False
            item["keep_mode"] = {}
            item.pop("relay_timers",None)
    issues = []
    tolerant = options.get("_bindings_store") is True
    for row in rows:
        if row["entity_id"] not in index:
            if tolerant:
                issues.append({"object_name": row["entity_id"], "category": "missing",
                               "reason": "Unadopted or removed switch entity"})
                continue
            raise CatalogError("Unadopted or removed switch entity: " + row["entity_id"])
        item = index[row["entity_id"]]
        if tolerant:
            item["configured_bindings"] = {k:parse_rule(v) for k,v in row["actions"].items()}
            item["disabled_actions"] = row.get("disabled_actions",[])
        try:
            item["keep_mode"] = validate_keep_mode(row.get("keep_mode", {}),
                                                   item.get("fingerprint", {}))
        except CatalogError as exc:
            if not tolerant:
                raise
            issues.append({"object_name": row["entity_id"], "category": "invalid_keep_mode",
                           "reason": str(exc)})
            continue
        if row.get("relay_timers"):item["relay_timers"]=dict(row["relay_timers"])
        item["maintenance_mode"] = row.get("maintenance_mode", False)
        supported = item.get("fingerprint", {}).get("actions", [])
        hardware = {key for key, (mode, _) in MODE_TO_RELAY.items()
                    if mode in item.get("fingerprint", {}).get("setting_keys", [])}
        for press, rule in row["actions"].items():
            if any(item["keep_mode"].get(k) == PHYSICAL
                   for k in action_channels(press, hardware)):
                reason = "Physical key cannot have Actions: " + press
                if not tolerant:
                    raise CatalogError(reason)
                issues.append({"object_name": row["entity_id"], "category": "invalid_binding",
                               "reason": reason})
                continue
            if press in row.get("disabled_actions", []):
                continue
            try:
                if press not in supported:
                    raise CatalogError("Unsupported Aqara action " + press + " for " + row["entity_id"])
                validate_action_policy(item["fingerprint"], item["keep_mode"], press)
                item["bindings"][press] = parse_rule(rule)
            except CatalogError as exc:
                if not tolerant:
                    raise
                issues.append({"object_name": row["entity_id"], "category": "invalid_binding",
                               "reason": str(exc)})
        item["enabled"] = row["enabled"]
    if tolerant:
        data["binding_problems"] = issues
        data["orphan_bindings"] = [r for r in rows if r["entity_id"] not in index]
    return data


def current(options: Mapping, path: Path = STORE_PATH) -> dict:
    return project(_read_profiles(path), options)


def store_scan(merged: Mapping, options: Mapping, path: Path = STORE_PATH) -> dict:
    rows = parse_rows(options)
    known = {row["entity_id"] for row in rows}
    for room in merged["rooms"]:
        for sw in room["switches"]:
            entity = sw["entity_id"]
            if entity not in known:
                row = {"entity_id": entity, "enabled": not options.get("_bindings_store", False), "actions": {}}
                if sw.get("mode_default") and not options.get("_bindings_store"):
                    row["keep_mode"] = dict(sw["mode_default"])
                rows.append(row)
                known.add(entity)
            elif not sw.get("mode_policy_initialized", False) and sw.get("mode_default"):
                # One-time adoption of keep_mode when upgrading from 0.1.9.
                # Afterward deleting keep_mode explicitly will NOT auto-recreate it.
                for row in rows:
                    if row["entity_id"] == entity and "keep_mode" not in row:
                        row["keep_mode"] = dict(sw["mode_default"])
    updated = {**options, "switches": render_rows(rows)}
    project(merged, updated)
    _save_profiles(path, merged)
    return updated
