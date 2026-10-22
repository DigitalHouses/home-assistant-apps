"""Strict, non-templated smart-light rule validation for Aqara action bindings.

Simple list: light.toggle. Rich mapping: allowlisted light service and data.
No arbitrary YAML service calls, scripts, relays or template expressions.
"""
from __future__ import annotations
from collections.abc import Mapping
import re

from .catalog import CatalogError

LIGHT_ID = re.compile(r"^light\.[a-z0-9_]+$")
SERVICES = {"light.toggle": "toggle", "light.turn_on": "on",
            "light.turn_off": "off"}
ON_FIELDS = {"brightness_pct", "brightness_step_pct",
             "color_temp_kelvin", "rgb_color", "transition"}
ALL_FIELDS = {"service", "targets"} | ON_FIELDS


def _integer(value: object, min_value: int, max_value: int, key: str) -> None:
    if type(value) is not int or not min_value <= value <= max_value:
        raise CatalogError(f"{key} must be an integer from {min_value} to {max_value}")


def validate_data(service: str, data: object) -> dict:
    """Validate supported HA light attributes, with no implicit coercions."""
    if service not in SERVICES or not isinstance(data, Mapping):
        raise CatalogError("Unsupported light service or data object")
    fields = set(data)
    if fields - ON_FIELDS:
        raise CatalogError("Unsupported smart-light field")
    if service == "light.turn_off" and fields - {"transition"}:
        raise CatalogError("light.turn_off permits only transition")
    if "brightness_pct" in data:
        _integer(data["brightness_pct"], 0, 100, "brightness_pct")
    if "brightness_step_pct" in data:
        _integer(data["brightness_step_pct"], -100, 100, "brightness_step_pct")
        if data["brightness_step_pct"] == 0:
            raise CatalogError("brightness_step_pct cannot be zero")
        if service != "light.turn_on":
            raise CatalogError("brightness_step_pct requires light.turn_on")
    if "brightness_pct" in data and "brightness_step_pct" in data:
        raise CatalogError("Choose brightness_pct or brightness_step_pct")
    if "color_temp_kelvin" in data:
        _integer(data["color_temp_kelvin"], 1000, 12000, "color_temp_kelvin")
    if "rgb_color" in data:
        rgb = data["rgb_color"]
        if (not isinstance(rgb, list) or len(rgb) != 3 or
                any(type(n) is not int or not 0 <= n <= 255 for n in rgb)):
            raise CatalogError("rgb_color requires three integers from 0 to 255")
    if "color_temp_kelvin" in data and "rgb_color" in data:
        raise CatalogError("Specify color_temp_kelvin or rgb_color, not both")
    if "brightness_step_pct" in data and (
            "color_temp_kelvin" in data or "rgb_color" in data):
        raise CatalogError("Brightness step cannot be combined with color")
    if "transition" in data:
        t = data["transition"]
        if type(t) not in (int, float) or not 0 <= t <= 60:
            raise CatalogError("transition must be from 0 to 60 seconds")
    return {key: list(value) if key == "rgb_color" else value
            for key, value in data.items()}


def parse_rule(value: object) -> dict:
    """Validate concise or rich action binding, with optional data PER target.

    Old forms stay valid:
       [light.a, light.b]                  -> one light.toggle
       {service, targets, brightness_pct} -> shared (v0.1.8 legacy) data
    New form:
       {service, targets: [{light.a: {brightness_pct: 70}}, light.b]}
       gives each light independent attributes, without global inheritance.
    """
    if isinstance(value, list):
        entries, service, data = value, "light.toggle", {}
    elif isinstance(value, Mapping):
        if set(value) - ALL_FIELDS or not {"service", "targets"} <= set(value):
            raise CatalogError(
                "Smart light action requires service, targets and optional light fields")
        service, entries = value["service"], value["targets"]
        data = {key: val for key, val in value.items()
                if key not in ("service", "targets")}
    else:
        raise CatalogError("Action must be a light list or a smart-light mapping")
    if not isinstance(service, str) or service not in SERVICES:
        raise CatalogError("Only light.toggle, light.turn_on, light.turn_off allowed")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
        raise CatalogError("Each Aqara action needs 1..16 lights")

    targets, target_data = [], {}
    for entry in entries:
        if isinstance(entry, str):
            entity, opts = entry, {}
        elif isinstance(entry, Mapping) and len(entry) == 1:
            entity, opts = next(iter(entry.items()))
            if not isinstance(opts, Mapping):
                raise CatalogError("Per-light parameters must be a mapping")
        else:
            raise CatalogError("Each target must be light.* or a one-key light mapping")
        if not isinstance(entity, str) or not LIGHT_ID.fullmatch(entity):
            raise CatalogError("Action targets must be light.* entity IDs")
        if entity in targets:
            raise CatalogError("Duplicate light target")
        targets.append(entity)
        if isinstance(entry, Mapping):
            target_data[entity] = validate_data(service, opts)

    if data and target_data:
        raise CatalogError("Do not combine shared and per-light parameters")
    verified = validate_data(service, data)
    return {"action": SERVICES[service], "targets": targets,
            "data": verified, "target_data": target_data}
