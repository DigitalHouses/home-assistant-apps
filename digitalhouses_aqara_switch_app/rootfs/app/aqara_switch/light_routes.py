"""Verified light.* -> Zigbee2MQTT mapping, stored at explicit Scan.

No guessed entity IDs, no raw user MQTT topics, no non-light relays.
Routes are persisted inside the existing private Adopt store.
"""
from __future__ import annotations
from collections import defaultdict, Counter
import json
import re
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
        # Z2M exposes color modes as composites named color_xy/color_hs,
        # both with property="color". The composite may lack access; the
        # nested attributes (x/y or hue/saturation) carry writable bits.
        if feat.get("type") == "composite" and feat.get("property") == "color":
            mode = feat.get("name")
            required = {"color_xy": {"x", "y"},
                        "color_hs": {"hue", "saturation"}}.get(mode)
            access = feat.get("access")
            if (required is not None and
                    (access is None or (type(access) is int and access & 2))):
                nested = feat.get("features")
                if isinstance(nested, list):
                    writable = {part.get("property") for part in nested
                                if isinstance(part, Mapping)
                                and type(part.get("access")) is int
                                and part["access"] & 2}
                    if required <= writable:
                        features[mode] = {}
            continue
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

def decode_groups(raw):
    if not isinstance(raw,bytes) or len(raw)>1_048_576:
        return []
    try:
        groups=json.loads(raw)
    except (ValueError,TypeError):
        return []
    if not isinstance(groups,list):
        return []
    return [g for g in groups if isinstance(g,dict)]

def group_routes(snapshot):
    """Only non-empty groups of verified single-light devices; use common capabilities."""
    groups=decode_groups(snapshot.get("groups"))
    devices=decode_bridge_devices(snapshot["devices"])
    by_ieee=defaultdict(list)
    for dev in devices:
        by_ieee[str(dev.get("ieee_address","")).lower()].append(dev)
    names=Counter(d.get("friendly_name") for d in devices if isinstance(d.get("friendly_name"),str))
    names.update(g.get("friendly_name") for g in groups if isinstance(g.get("friendly_name"),str))
    ids=Counter(g["id"] for g in groups if type(g.get("id")) is int)
    result={}
    for g in groups:
        gid,name,members=g.get("id"),g.get("friendly_name"),g.get("members")
        if (type(gid) is not int or not 1<=gid<=65535 or ids[gid]!=1
                or not isinstance(name,str) or names[name]!=1
                or any(x in ("",".","..","+","#","bridge","set","get","availability") or "+" in x or "#" in x for x in name.split("/"))
                or not isinstance(members,list) or not members):
            continue
        common=None; verified=[]; valid=True
        for member in members:
            if not isinstance(member,dict):
                valid=False;break
            ieee,ep=member.get("ieee_address"),member.get("endpoint")
            if not isinstance(ieee,str) or not re.fullmatch(r"0x[0-9a-fA-F]{16}",ieee) or type(ep) is not int or not 1<=ep<=240:
                valid=False;break
            ieee=ieee.lower()
            peers=by_ieee.get(ieee,[])
            if len(peers)!=1 or peers[0].get("disabled") is True:
                valid=False;break
            dev=peers[0]
            features=_light_features(dev)
            # Verify the actual member endpoint has the on/off input cluster.
            endpoints=dev.get("endpoints",{})
            endpoint=endpoints.get(str(ep),{}) if isinstance(endpoints,dict) else {}
            clusters=endpoint.get("clusters",{}).get("input",[]) if isinstance(endpoint,dict) and isinstance(endpoint.get("clusters",{}),dict) else []
            if not features or "genOnOff" not in clusters:
                valid=False;break
            member_name=dev.get("friendly_name")
            if not isinstance(member_name,str) or names[member_name]!=1:
                valid=False;break
            verified.append({"ieee":ieee,"endpoint":ep,"friendly_name":member_name})
            if common is None:
                common={k:dict(v) for k,v in features.items()}
            else:
                for k in list(common):
                    if k not in features:
                        common.pop(k);continue
                    if k=="state":
                        continue
                    for bound,fn in (("value_min",max),("value_max",min)):
                        if bound in features[k]:
                            common[k][bound]=fn(common[k].get(bound,features[k][bound]),features[k][bound])
                    if common[k].get("value_min",0)>common[k].get("value_max",1e9):
                        common.pop(k)
        if not valid or len({(m["ieee"],m["endpoint"]) for m in verified})!=len(verified):
            continue
        common["state"]={"readable":False} # never issue multicast /get
        result[gid]={"kind":"group","group_id":gid,"base_topic":snapshot["base_topic"],
                     "coordinator_ieee":snapshot["coordinator_ieee"],"friendly_name":name,
                     "members":sorted(verified,key=lambda m:(m["ieee"],m["endpoint"])),
                     "features":common}
    return result

def group_observed_state(route,net,fresh_fields):
    """Use group state when received; otherwise derive initial state from fresh members."""
    base,name=route["base_topic"],route["friendly_name"]
    states=net.get("states",{})
    if (base,name,"state") in fresh_fields:
        value=states.get(name,{}).get("state")
        if value in ("ON","OFF"):
            return value
    values=[]
    for member in route["members"]:
        m=member["friendly_name"]
        value=states.get(m,{}).get("state")
        if (base,m,"state") not in fresh_fields or value not in ("ON","OFF"):
            return None
        values.append(value)
    return "ON" if "ON" in values else "OFF" if values else None

def group_has_state(route,net,fresh_fields):
    return group_observed_state(route,net,fresh_fields) in ("ON","OFF")

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
    # Standard Z2M HA unique_id: <group id>_light_<base_topic>.
    # No match by editable friendly/entity name.
    by_uid=defaultdict(list)
    for e in ha_entities:
        if (isinstance(e,Mapping) and e.get("platform")=="mqtt" and e.get("disabled_by") is None
                and isinstance(e.get("entity_id"),str) and e["entity_id"].startswith("light.")
                and isinstance(e.get("unique_id"),str)):
            by_uid[e["unique_id"]].append(e["entity_id"])
    for snapshot in snapshots:
        for gid,route in group_routes(snapshot).items():
            choices=by_uid.get(f'{gid}_light_{snapshot["base_topic"]}',[])
            if len(choices)==1 and choices[0] not in routes:
                routes[choices[0]]=route
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
        if route.get("kind")=="group":
            live=group_routes({**net,"base_topic":route["base_topic"],"coordinator_ieee":coordinator})
            return live.get(route.get("group_id"))==route
        peers = [d for d in decode_bridge_devices(net["devices"])
                 if d.get("ieee_address", "").lower() == route.get("ieee")]
        if len(peers) != 1 or peers[0].get("friendly_name") != route.get("friendly_name"):
            return False
        return _light_features(peers[0]) == route.get("features")
    except (ValueError, TypeError, KeyError, CatalogError):
        return False
