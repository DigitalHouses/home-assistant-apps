"""Pure action planner for Aqara button events. Does not call Home Assistant.

Physical MQTT events are accepted only when declared in the saved model
profile. A binding must reference a narrowly allowlisted HA service.
"""
from __future__ import annotations
import re
from collections.abc import Mapping

_ENTITY_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
_SERVICE_MAP = {
    "light": {
        "toggle": "light.toggle", "on": "light.turn_on",
        "off": "light.turn_off",
    },
    "switch": {
        "toggle": "switch.toggle", "on": "switch.turn_on",
        "off": "switch.turn_off",
    },
    "input_boolean": {
        "toggle": "input_boolean.toggle", "on": "input_boolean.turn_on",
        "off": "input_boolean.turn_off",
    },
    "cover": {
        "toggle": "cover.toggle", "open": "cover.open_cover",
        "close": "cover.close_cover", "stop": "cover.stop_cover",
    },
    "fan": {
        "toggle": "fan.toggle", "on": "fan.turn_on", "off": "fan.turn_off",
    },
    "script": {"run": "script.turn_on"},
    "scene": {"activate": "scene.turn_on"},
}


class ActionError(ValueError):
    """Binding is invalid; do not execute any command."""


def plan_action(saved: Mapping, mqtt_action: str) -> dict | None:
    """Return one validated HA call, or None if the action is not bound.

    This is the only allowed service vocabulary; no user-controlled service
    string, script template, or arbitrary YAML automation is evaluated.
    """
    fingerprint = saved.get("fingerprint")
    if not isinstance(fingerprint, Mapping):
        raise ActionError("Saved switch has no validated hardware profile")
    supported = fingerprint.get("actions")
    if not isinstance(supported, list):
        raise ActionError("Supported physical actions are missing")
    if mqtt_action not in supported:
        return None
    bindings = saved.get("bindings")
    if not isinstance(bindings, Mapping):
        raise ActionError("Switch bindings must be a mapping")
    binding = bindings.get(mqtt_action)
    if binding is None:
        return None
    if not isinstance(binding, Mapping):
        raise ActionError("Action binding must be an object")
    mode = binding.get("action")
    targets = binding.get("targets")
    if not isinstance(mode, str) or not isinstance(targets, list) or not targets:
        raise ActionError("Action and nonempty targets list are required")
    if any(not isinstance(e, str) or not _ENTITY_ID.fullmatch(e)
           for e in targets):
        raise ActionError("Invalid HA target entity ID")
    if len(set(targets)) != len(targets):
        raise ActionError("Duplicate action targets")
    domains = {entity.split(".", 1)[0] for entity in targets}
    if len(domains) != 1:
        raise ActionError("Targets must belong to the same HA domain")
    domain = domains.pop()
    service = _SERVICE_MAP.get(domain, {}).get(mode)
    if service is None:
        raise ActionError("Action is not permitted for selected target domain")
    return {"service": service, "target": {"entity_id": list(targets)}}
