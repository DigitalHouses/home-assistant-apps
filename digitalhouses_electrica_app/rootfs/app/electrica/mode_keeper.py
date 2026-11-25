"""Per-key Aqara decoupled/ON policy and safe Maintenance transitions.

No physical writes at Scan. The runtime sends only explicitly managed
mode/relay keys after observing compatible Zigbee2MQTT hardware.
Battery remotes and other devices with no operation_mode have no keeper.
"""
from __future__ import annotations

from collections.abc import Mapping
import math
from .catalog import CatalogError, _exposes

MODE_TO_RELAY = {
    "main": ("operation_mode", "state"),
    "left": ("operation_mode_left", "state_left"),
    "right": ("operation_mode_right", "state_right"),
    "center": ("operation_mode_center", "state_center"),
}
KEEP_VALUE = "decoupled/ON"
PHYSICAL = "control_relay"
LOGICAL = "decoupled"
KEEP_OFF = "decoupled/OFF"
POLICIES = (PHYSICAL, LOGICAL, KEEP_VALUE, KEEP_OFF)


def held_relay(policy):
    return {KEEP_VALUE: "ON", KEEP_OFF: "OFF"}.get(policy)


def logical_policy(value):
    return value in (LOGICAL, KEEP_VALUE, KEEP_OFF)


def action_channels(action, channels):
    """Resolve only known key suffixes or a single unambiguous channel."""
    if action.endswith("_both"):
        return ("left", "right")
    suffix = action.rsplit("_", 1)[-1]
    if suffix in MODE_TO_RELAY:
        return (suffix,)
    return tuple(channels) if len(channels) == 1 else ()


def desired_mode(policy, maintenance=False):
    return PHYSICAL if maintenance or policy == PHYSICAL else LOGICAL


def global_policy(options: Mapping) -> dict:
    mode = options.get("maintenance_mode", False)
    delay = options.get("restore_delay", 0.6)
    if type(mode) is not bool:
        raise CatalogError("maintenance_mode must be boolean")
    if type(delay) not in (int, float) or not math.isfinite(delay) or not 0.1 <= delay <= 30:
        raise CatalogError("restore_delay must be between 0.1 and 30 seconds")
    return {"maintenance_mode": mode, "restore_delay": float(delay)}


def capabilities(device: Mapping) -> dict:
    """Discover writable Z2M mode AND corresponding writable physical relay.

    A mode which is not explicitly advertised as decoupled/control_relay is
    not inferred from the device model, name or an HA entity.
    """
    definition = device.get("definition")
    if (not isinstance(definition, Mapping) or
            str(definition.get("vendor", "")).casefold() != "aqara"):
        return {}
    features = {}
    for feature in _exposes(definition.get("exposes", [])):
        key = feature.get("property", feature.get("name"))
        if isinstance(key, str):
            features[key] = feature
    result = {}
    for key, (mode_field, relay_field) in MODE_TO_RELAY.items():
        mode, relay = features.get(mode_field), features.get(relay_field)
        if not isinstance(mode, Mapping) or not isinstance(relay, Mapping):
            continue
        values = mode.get("values")
        if (not isinstance(values, list) or
                not {"control_relay", "decoupled"} <= set(str(v) for v in values) or
                type(mode.get("access")) is not int or not mode["access"] & 2 or
                type(relay.get("access")) is not int or not relay["access"] & 2):
            continue
        result[key] = (mode_field, relay_field)
    return result


def capture_keep_mode(device: Mapping, state: Mapping) -> tuple[dict, list[str]]:
    """Initial Scan records only decoupled channels with observed relay status.

    OFF on first Scan still yields decoupled/ON as desired policy, but Scan
    does not energize anything. A missing/unwritable relay is not guessed.
    """
    result, warnings = {}, []
    features = capabilities(device)
    for key, (mode_field, relay_field) in features.items():
        if state.get(mode_field) != "decoupled":
            continue
        if state.get(relay_field) not in ("ON", "OFF"):
            warnings.append(f"{key}: relay state unknown; keep_mode not adopted")
            continue
        result[key] = KEEP_VALUE
    return result, warnings


def validate_keep_mode(keep: object, fingerprint: Mapping) -> dict:
    if not isinstance(keep, Mapping):
        raise CatalogError("keep_mode must be a channel mapping")
    allowed = set()
    settings = fingerprint.get("setting_keys", [])
    relays = fingerprint.get("relay_channels", [])
    for key, (mode_field, relay_field) in MODE_TO_RELAY.items():
        if mode_field in settings and relay_field in relays:
            allowed.add(key)
    if set(keep) - allowed:
        raise CatalogError("keep_mode contains unsupported or battery-only channels")
    for key, value in keep.items():
        if value not in POLICIES:
            raise CatalogError("Unsupported key policy")
    return dict(keep)


def maintained_switch(sw: Mapping, globals_: Mapping) -> bool:
    return bool(globals_["maintenance_mode"] or sw.get("maintenance_mode", False))


def mode_action_allowed(sw: Mapping, action: str, state: Mapping,
                        features: Mapping, maintenance: bool) -> bool:
    """Gate wired key actions on verified decoupled/ON; remotes need no mode."""
    if maintenance:
        return False
    if not features:
        # Battery/remotes have no operation_mode. Wired devices with mode
        # support but an unverified relay capability fail closed.
        modes = {f[0] for f in MODE_TO_RELAY.values()}
        return not ((modes & set(sw.get("fingerprint", {}).get("setting_keys", [])))
                    or sw.get("fingerprint", {}).get("relay_channels"))
    keep = sw.get("keep_mode", {})
    required = action_channels(action, features)
    if not required:
        return False
    for key in required:
        if key not in features or not logical_policy(keep.get(key)):
            return False
        mode, relay = features[key]
        if state.get(mode) != LOGICAL:
            return False
        if held_relay(keep[key]) and state.get(relay) != held_relay(keep[key]):
            return False
    return True


def next_repair(keep: Mapping, features: Mapping, state: Mapping,
                maintenance: bool) -> tuple[str, str] | None:
    """First actual deviation; mode precedes relay. Never write in Scan.

    Maintenance sets control_relay but NEVER changes relay power.
    Normal operation restores decoupled, then the selected relay state.
    Unknown states remain unknown instead of being written blindly.
    """
    for key in sorted(keep):
        fields = features.get(key)
        if fields is None:
            continue
        mode, relay = fields
        target_mode = desired_mode(keep[key], maintenance)
        seen = state.get(mode)
        if seen not in ("control_relay", "decoupled"):
            continue
        if seen != target_mode:
            return mode, target_mode
        wanted = held_relay(keep[key])
        if not maintenance and wanted and state.get(relay) in ("ON", "OFF") and state[relay] != wanted:
            return relay, wanted
    return None


def validate_action_policy(fingerprint: Mapping, keep: Mapping, action: str) -> None:
    """Reject wired key bindings for unmanaged control_relay channels.

    Battery remotes have no operation_mode property and are exempt.
    """
    hardware = {key for key, (mode, _) in MODE_TO_RELAY.items()
                if mode in fingerprint.get("setting_keys", [])}
    if not hardware:
        if fingerprint.get("relay_channels"):
            raise CatalogError("Input relay has no supported mode adapter")
        return
    required = set(action_channels(action, hardware))
    if not required:
        raise CatalogError("Ambiguous physical-key action " + action)
    if not required <= hardware or not all(logical_policy(keep.get(k)) for k in required):
        raise CatalogError(
            "Aqara action " + action + " requires decoupled/ON, decoupled/OFF or decoupled on " +
            ", ".join(sorted(required)))
