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
    """Produce a validated private action binding.

    The user config keeps its original short or rich syntax verbatim.
    """
    if isinstance(value, list):
        targets, service, data = value, "light.toggle", {}
    elif isinstance(value, Mapping):
        if set(value) - ALL_FIELDS or not {"service", "targets"} <= set(value):
            raise CatalogError("Smart light action requires service and targets only plus light fields")
        service, targets = value["service"], value["targets"]
        data = {k: v for k, v in value.items() if k not in ("service", "targets")}
    else:
        raise CatalogError("Action must be a list of lights or a smart-light mapping")
    if not isinstance(service, str) or service not in SERVICES:
        raise CatalogError("Only light.toggle, light.turn_on and light.turn_off are allowed")
    if not isinstance(targets, list) or not 1 <= len(targets) <= 16:
        raise CatalogError("Each Aqara action needs 1..16 lights")
    if any(not isinstance(t, str) or not LIGHT_ID.fullmatch(t) for t in targets):
        raise CatalogError("Action targets must be light.* entity IDs")
    if len(targets) != len(set(targets)):
        raise CatalogError("Duplicate light target")
    verified = validate_data(service, data)
    return {"action": SERVICES[service], "targets": list(targets), "data": verified}
