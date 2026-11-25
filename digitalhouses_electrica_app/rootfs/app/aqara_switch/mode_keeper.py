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
    if not isinstance(definition, Mapping):
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
        if value != KEEP_VALUE:
            raise CatalogError("Only confirmed decoupled/ON keep_mode is supported")
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
    if action.endswith("_both"):
        required = ("left", "right")
    elif action.rsplit("_", 1)[-1] in MODE_TO_RELAY:
        required = (action.rsplit("_", 1)[-1],)
    elif len(features) == 1:
        required = tuple(features)
    else:
        return False  # Ambiguous event on multikey physical switch.
    for key in required:
        if key not in features or keep.get(key) != KEEP_VALUE:
            return False
        mode, relay = features[key]
        if state.get(mode) != "decoupled" or state.get(relay) != "ON":
            return False
    return True


def next_repair(keep: Mapping, features: Mapping, state: Mapping,
                maintenance: bool) -> tuple[str, str] | None:
    """First actual deviation; mode precedes relay. Never write in Scan.

    Maintenance sets control_relay but NEVER changes relay power.
    Normal operation restores decoupled, then ON after mode confirmation.
    Unknown states remain unknown instead of being written blindly.
    """
    for key in sorted(keep):
        fields = features.get(key)
        if fields is None:
            continue
        mode, relay = fields
        target_mode = "control_relay" if maintenance else "decoupled"
        seen = state.get(mode)
        if seen not in ("control_relay", "decoupled"):
            continue
        if seen != target_mode:
            return mode, target_mode
        if not maintenance and state.get(relay) == "OFF":
            return relay, "ON"
    return None


def validate_action_policy(fingerprint: Mapping, keep: Mapping, action: str) -> None:
    """Reject wired key bindings for unmanaged control_relay channels.

    Battery remotes have no operation_mode property and are exempt.
    """
    hardware = {key for key, (mode, _) in MODE_TO_RELAY.items()
                if mode in fingerprint.get("setting_keys", [])}
    if not hardware:
        return
    if action.endswith("_both"):
        required = {"left", "right"}
    else:
        suffix = action.rsplit("_", 1)[-1]
        if suffix in MODE_TO_RELAY:
            required = {suffix}
        elif len(hardware) == 1:
            required = set(hardware)
        else:
            raise CatalogError("Ambiguous physical-key action " + action)
    if not required <= hardware or not required <= set(keep):
        raise CatalogError(
            "Aqara action " + action + " requires decoupled/ON on " +
            ", ".join(sorted(required)))
