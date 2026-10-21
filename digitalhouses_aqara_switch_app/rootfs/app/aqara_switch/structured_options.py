"""One-time legacy migration and flat, user-friendly Supervisor options.

Authoritative physical fingerprint/Adopt settings live in /data, NOT editable
Supervisor options. Users edit only registered switches and explicit key
assignments. Never silently replace a captured Mode Keeper baseline.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
import os
from pathlib import Path
import re

from .catalog import CatalogError, validate_config

STORE_PATH = Path("/data/adopted_switches.json")
_IEEE = re.compile(r"^0x[0-9a-fA-F]{16}$")
_LIGHT = re.compile(r"^light\.[a-z0-9_]+$")


def _read_profiles(path: Path) -> dict:
    if not path.exists():
        return {"rooms": []}
    try:
        raw = path.read_bytes()
        if len(raw) > 1_048_576:
            raise CatalogError("Adopt store exceeds 1 MiB")
        return validate_config(json.loads(raw))
    except (OSError, ValueError, TypeError) as exc:
        raise CatalogError("Adopt store is invalid; never overwrite it") from exc


def _save_profiles(path: Path, config: Mapping) -> None:
    verified = validate_config(config)
    encoded = json.dumps(verified, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 1_048_576:
        raise CatalogError("Adopt store exceeds 1 MiB")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def switch_rows(config: Mapping) -> list[dict]:
    rows = []
    for room in config["rooms"]:
        for sw in room["switches"]:
            rows.append({"ieee": sw["ieee"], "name": sw["logical_name"],
                         "enabled": sw.get("enabled", True)})
    return rows


def binding_rows(config: Mapping) -> list[dict]:
    rows = []
    for room in config["rooms"]:
        for sw in room["switches"]:
            for press, binding in (sw.get("bindings") or {}).items():
                targets = binding.get("targets", []) if isinstance(binding, Mapping) else []
                if (binding.get("action") != "toggle" or not isinstance(targets, list)
                        or len(targets) != 1 or not isinstance(targets[0], str)
                        or not _LIGHT.fullmatch(targets[0])):
                    raise CatalogError("Cannot automatically migrate a non-light.toggle binding")
                rows.append({"ieee": sw["ieee"], "press": press, "light": targets[0]})
    return rows


def project(profiles: Mapping, options: Mapping) -> dict:
    """Compose runtime tree from immutable adopted metadata + flat user choices."""
    if not isinstance(options.get("switches"), list) or not isinstance(options.get("bindings"), list):
        raise CatalogError("Supervisor switches and bindings must be lists")
    data = validate_config(profiles)
    saved = {}
    for room in data["rooms"]:
        for sw in room["switches"]:
            ieee = sw["ieee"].lower()
            if ieee in saved:
                raise CatalogError("Adopt store contains duplicate switch IEEE")
            saved[ieee] = sw
            sw["bindings"] = {}
    selected = {}
    for item in options["switches"]:
        if (not isinstance(item, Mapping) or
                not isinstance(item.get("ieee"), str) or
                not _IEEE.fullmatch(item["ieee"]) or
                not isinstance(item.get("name"), str) or not item["name"] or
                not isinstance(item.get("enabled"), bool)):
            raise CatalogError("Invalid structured switch entry")
        ieee = item["ieee"].lower()
        if ieee not in saved or saved[ieee]["logical_name"] != item["name"]:
            raise CatalogError("Configured switch was not adopted or name does not match")
        if ieee in selected:
            raise CatalogError("Duplicate switch IEEE in Supervisor options")
        selected[ieee] = item["enabled"]
    seen = set()
    for binding in options["bindings"]:
        if not isinstance(binding, Mapping):
            raise CatalogError("Invalid button binding")
        ieee, press, target = (binding.get("ieee"), binding.get("press"), binding.get("light"))
        if (not isinstance(ieee, str) or not _IEEE.fullmatch(ieee) or
                not isinstance(press, str) or not press or
                not isinstance(target, str) or not _LIGHT.fullmatch(target)):
            raise CatalogError("Binding requires valid IEEE, press and light entity ID")
        ieee = ieee.lower()
        if ieee not in selected:
            raise CatalogError("Binding references a switch not in Supervisor options")
        if press not in saved[ieee]["fingerprint"].get("actions", []):
            raise CatalogError("Binding action is not supported by adopted switch")
        if (ieee, press) in seen:
            raise CatalogError("Duplicate binding for one button press")
        seen.add((ieee, press))
        saved[ieee]["bindings"][press] = {"action": "toggle", "targets": [target]}
    for room in data["rooms"]:
        for sw in room["switches"]:
            sw["enabled"] = selected.get(sw["ieee"].lower(), False)
    return data


def current(options: Mapping, path: Path = STORE_PATH) -> dict:
    if "switches" in options and "bindings" in options:
        return project(_read_profiles(path), options)
    from .configuration import parse_legacy
    return parse_legacy(options)


def migrate(options_client, path: Path = STORE_PATH) -> dict:
    """Migrate existing installations at startup, without deleting legacy input.

    Keeps legacy text as temporary rollback copy until a separate schema-removal
    release. Writes profiles first and validates a round-trip before options.
    """
    options = options_client.read()
    if "switches" in options and "bindings" in options:
        current(options, path)
        return options
    from .configuration import parse_legacy
    legacy = parse_legacy(options)
    switches = switch_rows(legacy)
    bindings = binding_rows(legacy)
    if path.exists():
        stored = _read_profiles(path)
        # Previously partially migrated state must match exactly; fail closed.
        if stored != validate_config(legacy):
            raise CatalogError("Migration blocked: Adopt store conflicts with old YAML")
    else:
        _save_profiles(path, legacy)
    updated = {**options, "switches": switches, "bindings": bindings}
    # Retain old YAML verbatim for rollback; not a writable control source.
    projected = project(_read_profiles(path), updated)
    # Validate no lost hardware or bindings prior to writing Supervisor options.
    if len(switch_rows(projected)) != len(switches):
        raise CatalogError("Migration lost an adopted switch")
    options_client.write(updated)
    return updated


def store_scan(merged: Mapping, options: Mapping, path: Path = STORE_PATH) -> dict:
    """Stage auto-adopted profiles and editable list, preserving user choices."""
    existing = options.get("switches", [])
    if not isinstance(existing, list):
        raise CatalogError("Invalid previous switches")
    by_ieee = {row["ieee"].lower(): row for row in existing}
    updated_rows = [deepcopy(row) for row in existing]
    for row in switch_rows(merged):
        if row["ieee"].lower() not in by_ieee:
            updated_rows.append(row)
    updated = {**options, "switches": updated_rows}
    project(merged, updated)  # preflight all retained UI bindings
    _save_profiles(path, merged)
    return updated
