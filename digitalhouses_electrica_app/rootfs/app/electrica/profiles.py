"""Read-only consumer contract for the future global home-mode module."""
from collections.abc import Mapping
from .catalog import CatalogError

# Temporary development adapter only. The future producer owns night_mode
# (on/off); its final MQTT topics and profile payloads are not agreed yet.
TOPIC = "DigitalHouses/Global/day_night/state"
SOURCES = {"day","night","current"}
FIELDS = {"brightness_pct","color_temp_kelvin","rgb_color","volume_pct","color_mode"}

def integer(value,lo,hi):
    return type(value) is int and lo<=value<=hi

def validate_snapshot(value):
    """One atomic retained snapshot; no guessed profiles or persisted copies."""
    if not isinstance(value,dict) or set(value)!={"schema","mode","day","night"} or type(value["schema"]) is not int or value["schema"]!=1 or value["mode"] not in ("day","night"):
        raise CatalogError("Invalid global home-mode snapshot")
    for name in ("day","night"):
        row=value[name]
        if not isinstance(row,dict) or set(row)!=FIELDS:
            raise CatalogError("Incomplete global profile")
        if not integer(row["brightness_pct"],1,100) or not integer(row["color_temp_kelvin"],1000,12000) or not integer(row["volume_pct"],0,100):
            raise CatalogError("Invalid global profile value")
        rgb=row["rgb_color"]
        if not isinstance(rgb,list) or len(rgb)!=3 or any(not integer(v,0,255) for v in rgb):
            raise CatalogError("Invalid global RGB")
        if row["color_mode"] not in ("cct","rgb"):
            raise CatalogError("Invalid global color preference")
    return value

def source(data):
    if "profile" not in data:return None
    value=data["profile"]
    if not isinstance(value,str) or value not in SOURCES or set(data)!={"profile"}:
        raise CatalogError("Profile reference cannot contain local parameters")
    return value

def supported_light(target):
    return bool(target.get("brightness") or target.get("cct") or target.get("rgb"))

def resolve(data,target,snapshot,domain):
    ref=source(data)
    if ref is None:return data
    if snapshot is None:raise CatalogError("Global Day/Night module unavailable")
    row=snapshot[snapshot["mode"] if ref=="current" else ref]
    if domain=="media_player":
        if "volume" not in target.get("operations",[]):
            raise CatalogError("Volume not supported")
        return {"volume_pct":row["volume_pct"]}
    if not supported_light(target):raise CatalogError("Light has no profile capabilities")
    result={}
    if target.get("brightness"):result["brightness_pct"]=row["brightness_pct"]
    use_cct=target.get("cct") and (not target.get("rgb") or row["color_mode"]=="cct")
    if use_cct:
        lo,hi=target.get("min_kelvin"),target.get("max_kelvin")
        if type(lo) is not int or type(hi) is not int or not lo<=hi:
            raise CatalogError("Light CCT range unknown")
        result["color_temp_kelvin"]=max(lo,min(hi,row["color_temp_kelvin"]))
    elif target.get("rgb"):result["rgb_color"]=list(row["rgb_color"])
    if not result:raise CatalogError("No applicable profile parameters")
    return result

def resolve_commands(commands,catalog,snapshot):
    """Resolve only profile references. Keep plain and legacy commands intact."""
    output,skipped,unresolved_toggles=[],[],{}
    for call in commands:
        data=call.get("data",{})
        if "profile" not in data:
            output.append(call);continue
        for eid in call["target"]["entity_id"]:
            try:
                if eid not in catalog:raise CatalogError("Profile target unavailable")
                resolved=resolve(data,catalog[eid],snapshot,eid.split(".")[0])
                output.append({"service":call["service"],"target":{"entity_id":[eid]},"data":resolved})
            except CatalogError as exc:
                if call["service"]=="light.toggle":
                    # Keep the target in the shared toggle decision. OFF is
                    # independent of the global parameters; ON is not.
                    unresolved_toggles[eid]=str(exc)
                    output.append({"service":"light.toggle","target":{"entity_id":[eid]}})
                else:
                    skipped.append({"light":eid,"reason":str(exc)})
    return output,skipped,unresolved_toggles


def adaptation_targets(config):
    """Enabled dynamic assignments only; ambiguous mixed policies fail closed.

    OFF is not a parameter owner. Do not infer the active profile from ON.
    Return candidates and conflicts, including overlapping Z2M groups.
    """
    kinds={}
    for room in config["rooms"]:
        for sw in room["switches"]:
            if not sw.get("enabled",False) or sw.get("maintenance_mode",False):continue
            for action,rule in sw.get("bindings",{}).items():
                if action in sw.get("disabled_actions",[]):continue
                for eid in rule.get("targets",[]):
                    op=rule.get("target_operations",{}).get(eid,rule.get("action"))
                    if ((eid.startswith("light.") and op in ("on","toggle")) or
                            (eid.startswith("media_player.") and op=="volume")):
                        data=rule.get("target_data",{}).get(eid,rule.get("data",{}))
                        kinds.setdefault(eid,set()).add(data.get("profile")=="current")
    routes=config.get("light_routes",{})
    def physical_ids(eid):
        route=routes.get(eid)
        if not route:return {("ha",eid)}
        base=route["base_topic"]
        if route.get("kind")=="group":
            return {(base,m["ieee"]) for m in route["members"]}
        return {(base,route.get("ieee",route["friendly_name"]))}
    fixed=set().union(*(physical_ids(eid) for eid,v in kinds.items() if False in v))
    candidates={eid for eid,v in kinds.items() if True in v}
    conflicts={eid for eid in candidates if physical_ids(eid)&fixed}
    return sorted(candidates-conflicts),sorted(conflicts)

def group_already_on(route,net,availability,fresh_fields,shadows):
    base=route["base_topic"]
    return all((base,m["friendly_name"],"state") in fresh_fields
               and availability.get((base,m["friendly_name"]))=="online"
               and (base,m["friendly_name"]) not in shadows
               and net.get("states",{}).get(m["friendly_name"],{}).get("state")=="ON"
               for m in route["members"]) and bool(route["members"])
