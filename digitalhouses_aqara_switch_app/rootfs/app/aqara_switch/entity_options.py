"""Fresh v0.1.6-only switch configuration: HA entity key -> button actions.

No migration. Only existing HA switch.* entity_ids are accepted. Hardware
fingerprint/mode baseline is private App state, separate from user bindings.
"""
from __future__ import annotations
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
import re
import yaml

from .catalog import CatalogError, validate_config
from .structured_options import _read_profiles, _save_profiles

STORE_PATH = Path("/data/adopted_switches.json")
_ENTITY = re.compile(r"^switch\.[a-z0-9_]+$")
_LIGHT = re.compile(r"^light\.[a-z0-9_]+$")


def parse_rows(options: Mapping) -> list[dict]:
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
            raise CatalogError("Switch key must be an existing switch.* entity_id")
        if entity_id in unique:
            raise CatalogError("Duplicate logical switch entity_id")
        unique.add(entity_id)
        if not isinstance(value, Mapping) or set(value) != {"enabled", "actions"}:
            raise CatalogError("Switch requires enabled and actions only")
        if not isinstance(value["enabled"], bool) or not isinstance(value["actions"], Mapping):
            raise CatalogError("enabled must be boolean, actions must be mapping")
        actions = {}
        for press, targets in value["actions"].items():
            if not isinstance(press, str) or not press:
                raise CatalogError("Invalid action name")
            if not isinstance(targets, list) or not 1 <= len(targets) <= 16:
                raise CatalogError("Each action needs between 1 and 16 lights")
            if any(not isinstance(t, str) or not _LIGHT.fullmatch(t) for t in targets):
                raise CatalogError("Action targets must be light.* entity IDs")
            if len(targets) != len(set(targets)):
                raise CatalogError("Duplicate light target")
            actions[press] = list(targets)
        result.append({"entity_id": entity_id, "enabled": value["enabled"],
                       "actions": actions})
    return result


def render_rows(rows: list[dict]) -> str:
    return yaml.safe_dump([
        {row["entity_id"]: {"enabled": row["enabled"], "actions": row["actions"]}}
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
                raise CatalogError("Adopted hardware lacks unique HA switch entity_id")
            if entity_id in index:
                raise CatalogError("Duplicate adopted HA switch entity_id")
            index[entity_id] = item
            item["bindings"] = {}
            item["enabled"] = False
    for row in rows:
        if row["entity_id"] not in index:
            raise CatalogError("Unadopted or removed switch entity: " + row["entity_id"])
        item = index[row["entity_id"]]
        supported = item.get("fingerprint", {}).get("actions", [])
        for press, targets in row["actions"].items():
            if press not in supported:
                raise CatalogError("Unsupported Aqara action " + press + " for " + row["entity_id"])
            item["bindings"][press] = {"action": "toggle", "targets": targets}
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
                rows.append({"entity_id": entity, "enabled": True, "actions": {}})
                known.add(entity)
    updated = {**options, "switches": render_rows(rows)}
    project(merged, updated)
    _save_profiles(path, merged)
    return updated
