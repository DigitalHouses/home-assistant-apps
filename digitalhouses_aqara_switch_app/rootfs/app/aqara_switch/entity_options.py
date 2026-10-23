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
from .mode_keeper import global_policy, validate_keep_mode, validate_action_policy
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
    result, unique = [], set()
    for row in rows:
        if not isinstance(row, Mapping) or len(row) != 1:
            raise CatalogError("Each switch row must have exactly one entity_id key")
        entity_id, value = next(iter(row.items()))
        if not isinstance(entity_id, str) or not _ENTITY.fullmatch(entity_id):
            raise CatalogError("Switch key must be switch.* (HA entity or logical config key)")
        if entity_id in unique:
            raise CatalogError("Duplicate logical switch entity_id")
        unique.add(entity_id)
        if (not isinstance(value, Mapping) or
                not {"enabled", "actions"} <= set(value) or
                set(value) - {"enabled", "actions", "keep_mode", "maintenance_mode"}):
            raise CatalogError("Switch requires enabled and actions, optionally keep_mode/maintenance_mode")
        if "maintenance_mode" in value and type(value["maintenance_mode"]) is not bool:
            raise CatalogError("Local maintenance_mode must be boolean")
        keep = value.get("keep_mode", {})
        if not isinstance(keep, Mapping):
            raise CatalogError("keep_mode must be a mapping")
        for key, desired in keep.items():
            if key not in ("left", "right", "center", "main") or desired != "decoupled/ON":
                raise CatalogError("keep_mode supports only decoupled/ON for known channels")
        if not isinstance(value["enabled"], bool) or not isinstance(value["actions"], Mapping):
            raise CatalogError("enabled must be boolean, actions must be mapping")
        actions = {}
        for press, rule in value["actions"].items():
            if not isinstance(press, str) or not press:
                raise CatalogError("Invalid action name")
            parse_rule(rule)  # fail closed before persisting user configuration
            actions[press] = list(rule) if isinstance(rule, list) else dict(rule)
        item = {"entity_id": entity_id, "enabled": value["enabled"], "actions": actions}
        if "maintenance_mode" in value:
            item["maintenance_mode"] = value["maintenance_mode"]
        if "keep_mode" in value:
            item["keep_mode"] = dict(keep)
        result.append(item)
    return result


def render_rows(rows: list[dict]) -> str:
    return yaml.safe_dump([
        {row["entity_id"]: {key: row[key] for key in ("enabled", "maintenance_mode", "keep_mode", "actions") if key in row}}
        for row in rows], allow_unicode=True, sort_keys=False,
        default_flow_style=False)


def project(profiles: Mapping, options: Mapping) -> dict:
    data = validate_config(profiles)
    rows = parse_rows(options)
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
            item["enabled"] = False
            item["maintenance_mode"] = False
            item["keep_mode"] = {}
    for row in rows:
        if row["entity_id"] not in index:
            raise CatalogError("Unadopted or removed switch entity: " + row["entity_id"])
        item = index[row["entity_id"]]
        item["keep_mode"] = validate_keep_mode(row.get("keep_mode", {}),
                                                 item.get("fingerprint", {}))
        item["maintenance_mode"] = row.get("maintenance_mode", False)
        supported = item.get("fingerprint", {}).get("actions", [])
        for press, rule in row["actions"].items():
            if press not in supported:
                raise CatalogError("Unsupported Aqara action " + press + " for " + row["entity_id"])
            validate_action_policy(item["fingerprint"], item["keep_mode"], press)
            item["bindings"][press] = parse_rule(rule)
        item["enabled"] = row["enabled"]
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
                row = {"entity_id": entity, "enabled": True, "actions": {}}
                if sw.get("mode_default"):
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
