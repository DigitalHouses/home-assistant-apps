"""Verified light.* -> Zigbee2MQTT mapping, stored at explicit Scan.

No guessed entity IDs, no raw user MQTT topics, no non-light relays.
Routes are persisted inside the existing private Adopt store.
"""
from __future__ import annotations
from collections import defaultdict
from collections.abc import Mapping
from .catalog import CatalogError, _exposes, decode_bridge_devices
from .ha_registry import _matched_devices

def _light_features(device: Mapping) -> dict | None:
    definition = device.get("definition")
    if not isinstance(definition, Mapping):
        return None
    try:
        lights = [f for f in _exposes(definition.get("exposes", []))
                  if f.get("type") == "light"]
    except CatalogError:
        return None
    # Multi-endpoint/ambiguous light devices are deliberately not guessed.
    if len(lights) != 1:
        return None
    features = {}
    for feat in _exposes(lights[0].get("features", [])):
        key = feat.get("property", feat.get("name"))
        if isinstance(key, str) and type(feat.get("access")) is int:
            if feat["access"] & 2:
                numeric = {}
                if feat.get("type") == "numeric":
                    for name in ("value_min", "value_max"):
                        val = feat.get(name)
                        if type(val) in (int, float):
                            numeric[name] = val
                if key == "state":
                    numeric["readable"] = bool(feat["access"] & 4)
                features[key] = numeric
    if "state" not in features:
        return None
    return features

def discover_routes(snapshots: list[dict], ha_devices: object,
                    ha_entities: object) -> dict:
    """Map HA light IDs to confirmed (coordinator, IEEE, friendly_name).

    HA is consulted ONLY at an operator-triggered Scan. Runtime is MQTT-only.
    """
    devices = {}
    duplicates = set()
    for snapshot in snapshots:
        base, coordinator = snapshot["base_topic"], snapshot["coordinator_ieee"]
        for dev in decode_bridge_devices(snapshot["devices"]):
            ieee = dev.get("ieee_address")
            if not isinstance(ieee, str) or not ieee.startswith("0x"):
                continue
            feature = _light_features(dev)
            if feature is None or dev.get("disabled") is True:
                continue
            name = dev.get("friendly_name")
            if not isinstance(name, str) or not name or name.endswith(("/set", "/get", "/availability")):
                continue
            if ieee.lower() in devices:
                duplicates.add(ieee.lower())
            devices[ieee.lower()] = (base, coordinator, name, feature)
    for ieee in duplicates:
        devices.pop(ieee, None)
    if not devices:
        return {}
    owners = _matched_devices(ha_devices, set(devices))
    if not isinstance(ha_entities, list):
        raise CatalogError("Invalid HA Entity Registry")
    by_device = defaultdict(list)
    for entity in ha_entities:
        if not isinstance(entity, Mapping):
            raise CatalogError("Invalid HA light registry entry")
        eid = entity.get("entity_id")
        if (isinstance(eid, str) and eid.startswith("light.") and
                entity.get("disabled_by") is None and
                entity.get("platform") in (None, "mqtt") and
                isinstance(entity.get("device_id"), str)):
            by_device[entity["device_id"]].append(eid)
    routes = {}
    for ieee, (base, coordinator, friendly, features) in devices.items():
        linked = owners.get(ieee, [])
        if len(linked) != 1:
            continue
        lights = sorted(set(by_device.get(linked[0].get("id"), [])))
        if len(lights) != 1:  # Avoid binding multi-endpoint lights to wrong endpoints.
            continue
        eid = lights[0]
        if eid in routes:
            routes.pop(eid, None)
            continue
        routes[eid] = {
            "base_topic": base, "coordinator_ieee": coordinator,
            "ieee": ieee, "friendly_name": friendly, "features": features,
        }
    return routes

def current_route(route: Mapping, net: Mapping) -> bool:
    """Prove saved route still matches the live Z2M coordinator and device."""
    if not isinstance(net.get("info"), bytes) or not isinstance(net.get("devices"), bytes):
        return False
    import json
    try:
        coordinator = json.loads(net["info"])["coordinator"]["ieee_address"].lower()
        if coordinator != route.get("coordinator_ieee"):
            return False
        peers = [d for d in decode_bridge_devices(net["devices"])
                 if d.get("ieee_address", "").lower() == route.get("ieee")]
        if len(peers) != 1 or peers[0].get("friendly_name") != route.get("friendly_name"):
            return False
        return _light_features(peers[0]) == route.get("features")
    except (ValueError, TypeError, KeyError, CatalogError):
        return False
