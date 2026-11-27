"""Read-only consumer contract for the future global home-mode module."""
import math
from .catalog import CatalogError

STATE_TOPIC = "DigitalHouses/Global/night_mode/state"
PROFILES_TOPIC = "DigitalHouses/Global/night_mode/profiles"
TOPICS = (STATE_TOPIC, PROFILES_TOPIC)
SOURCES = {"day","night","current"}
PERCENT_FIELDS = {"brightness","volume"}
BOOLEAN_FIELDS = {"voice_notifications_enabled","noncritical_sound_notifications_enabled"}
FIELDS = PERCENT_FIELDS | BOOLEAN_FIELDS | {"color_temp_kelvin","rgb_color","transition_seconds"}

def integer(value,lo,hi):
    return type(value) is int and lo<=value<=hi

def validate_profiles(value):
    """System Globals publishes both complete profiles, with explicit nulls."""
    if not isinstance(value,dict) or set(value)!={"day","night"}:
        raise CatalogError("Expected day and night profiles")
    for row in value.values():
        if not isinstance(row,dict) or set(row)!=FIELDS:
            raise CatalogError("Incomplete global profile")
        for field in PERCENT_FIELDS:
            if row[field] is not None and not integer(row[field],0,100):
                raise CatalogError("Invalid global percent")
        for field in BOOLEAN_FIELDS:
            if row[field] is not None and type(row[field]) is not bool:
                raise CatalogError("Invalid global flag")
        transition=row["transition_seconds"]
        if transition is not None and (type(transition) not in (int,float) or not 0<=transition or not math.isfinite(transition)):
            raise CatalogError("Invalid transition")
        cct,rgb=row["color_temp_kelvin"],row["rgb_color"]
        if cct is not None and not integer(cct,2000,6000):
            raise CatalogError("Invalid global CCT")
        if rgb is not None and not (isinstance(rgb,list) and len(rgb)==3 and all(integer(v,0,255) for v in rgb)):
            raise CatalogError("Invalid global RGB")
    return value

def state_mode(raw):
    return {b"on":"night",b"off":"day"}.get(raw)

def snapshot(mode,values):
    # Fixed references work even before the first mode arrives.
    return {"mode":mode,**(values or {})} if mode is not None or values is not None else None

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
    name=snapshot.get("mode") if ref=="current" else ref
    row=snapshot.get(name) if name else None
    if row is None:raise CatalogError("Global profile or mode unavailable")
    if domain=="media_player":
        if "volume" not in target.get("operations",[]):
            raise CatalogError("Volume not supported")
        if row["volume"] is None:raise CatalogError("Global volume is unset")
        return {"volume_pct":row["volume"]}
    if not supported_light(target):raise CatalogError("Light has no profile capabilities")
    result={}
    if target.get("brightness") and row["brightness"] is not None:
        result["brightness_pct"]=row["brightness"]
    if row["color_temp_kelvin"] is not None and target.get("cct"):
        lo,hi=target.get("min_kelvin"),target.get("max_kelvin")
        if type(lo) is int and type(hi) is int and 0<lo<=hi:
            result["color_temp_kelvin"]=max(lo,min(hi,row["color_temp_kelvin"]))
    if "color_temp_kelvin" not in result and row["rgb_color"] is not None and target.get("rgb"):
        result["rgb_color"]=list(row["rgb_color"])
    if not result:raise CatalogError("No applicable profile parameters")
    if result.get("brightness_pct")==0:
        # Explicit zero illumination has no color requirement.
        result={"brightness_pct":0}
    if target.get("transition") and row["transition_seconds"] is not None:
        # Existing engine's validated transition range is 0..60 seconds.
        result["transition"]=min(60,row["transition_seconds"])
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
    for row in config.get("sensor_bindings",{}).values():
        if row.get("enabled"):
            for a in row["assignments"]:
                if a["entity_id"].startswith("light."):
                    kinds.setdefault(a["entity_id"],set()).add(a.get("data",{}).get("profile")=="current")
    for row in config.get("schedules",{}).values():
        if not row["enabled"]:continue
        for a in row["assignments"]:
            if (a["entity_id"].startswith("light.") and a["operation"]=="on") or (a["entity_id"].startswith("media_player.") and a["operation"]=="volume"):
                kinds.setdefault(a["entity_id"],set()).add(a.get("data",{}).get("profile")=="current")
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


def apply_zero_to_ha_plans(plans,zero_ids):
    """Keep legacy targets intact even when their parameters coalesce with a profile."""
    for call in plans:
        if call["service"]!="light.turn_on":
            yield call
            continue
        ids=call["target"]["entity_id"]
        zero=[eid for eid in ids if eid in zero_ids]
        other=[eid for eid in ids if eid not in zero_ids]
        if zero:
            yield {"service":"light.turn_off","target":{"entity_id":zero},
                   "data":{k:v for k,v in call.get("data",{}).items() if k=="transition"}}
        if other:
            yield {**call,"target":{"entity_id":other}}
