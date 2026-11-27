"""Motion/occupancy/presence inputs and exact same-device Lux capabilities."""
import math
import re
from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from .catalog import CatalogError
from .light_rules import parse_rule

CLASSES={"motion","occupancy","presence"}
MAX_LUX_AGE=900  # seconds; stale measurements must not cause automatic ON

def is_source(eid):
    return isinstance(eid,str) and re.fullmatch(r"binary_sensor\.[a-z0-9_]+",eid) is not None

def is_lux(state):
    a=state.get("attributes",{})
    return (state.get("entity_id","").startswith("sensor.") and
            a.get("device_class")=="illuminance" and a.get("unit_of_measurement")=="lx")

def is_presence(state):
    return is_source(state.get("entity_id")) and state.get("attributes",{}).get("device_class") in CLASSES

def validate_row(row):
    if (not isinstance(row,Mapping) or not is_source(row.get("entity_id"))
            or set(row)-{"entity_id","enabled","assignments","lux_entity_id","lux_threshold"}
            or type(row.get("enabled")) is not bool
            or not isinstance(row.get("assignments"),list) or len(row["assignments"])>16):
        raise CatalogError("Invalid sensor assignment")
    lux,threshold=row.get("lux_entity_id"),row.get("lux_threshold")
    if lux is not None or threshold is not None:
        if not isinstance(lux,str) or not re.fullmatch(r"sensor\.[a-z0-9_]+",lux) or type(threshold) not in (int,float) or not 0<=threshold<=1000000 or not math.isfinite(threshold):
            raise CatalogError("Lux requires a source and a nonnegative threshold")
    elif "lux_entity_id" in row or "lux_threshold" in row:
        raise CatalogError("Omit both Lux fields when unavailable")
    assignments=[]
    for a in row["assignments"]:
        if not isinstance(a,Mapping) or set(a)-{"entity_id","operation","data","off_delay_seconds","when","night_data","modes"} or a.get("operation")!="on" or not isinstance(a.get("entity_id"),str) or not a["entity_id"].startswith(("light.","switch.")):
            raise CatalogError("Motion/Presence supports explicit ON for lights and switches")
        if "modes" in a:
            if set(a)!={"entity_id","operation","modes"}:
                raise CatalogError("Do not mix mode blocks with legacy fields")
            modes=a["modes"]
            if not isinstance(modes,Mapping) or set(modes)!={"day","night"}:
                raise CatalogError("Both Day and Night settings are required")
            for block in modes.values():
                if (not isinstance(block,Mapping) or set(block)-{"enabled","data","off_delay_seconds"}
                        or type(block.get("enabled")) is not bool or not isinstance(block.get("data"),Mapping)):
                    raise CatalogError("Invalid Day/Night settings")
                if "off_delay_seconds" in block and (type(block["off_delay_seconds"]) is not int or not 0<=block["off_delay_seconds"]<=86400):
                    raise CatalogError("Auto-OFF delay must be 0..86400 seconds or omitted")
                if "brightness_step_pct" in block["data"] and modes["day"]!=modes["night"]:
                    raise CatalogError("Mode-specific parameters require absolute brightness")
                parse_rule({"assignments":[{"entity_id":a["entity_id"],"operation":"on","data":block["data"]}]})
            assignments.append({"entity_id":a["entity_id"],"operation":"on","data":{}})
            continue
        delay=a.get("off_delay_seconds")
        if delay is not None and (type(delay) is not int or not 0<=delay<=86400):
            raise CatalogError("Auto-OFF delay must be 0..86400 seconds or omitted")
        when=a.get("when","always")
        if when not in ("always","day","night"):
            raise CatalogError("Invalid Day/Night condition")
        primary={k:v for k,v in a.items() if k not in ("off_delay_seconds","when","night_data")}
        if "night_data" in a:
            if when!="always" or not a["entity_id"].startswith("light."):
                raise CatalogError("Separate night parameters require an always-enabled light")
            night={**primary,"data":a["night_data"]}
            parse_rule({"assignments":[night]})
            if "brightness_step_pct" in a["night_data"] or "brightness_step_pct" in primary.get("data",{}):
                raise CatalogError("Mode-specific parameters require absolute brightness")
        assignments.append(primary)
    if assignments:parse_rule({"assignments":assignments})
    return deepcopy(dict(row))

def discover(registries,states):
    devices,areas,entities=registries
    counts=Counter(e.get("entity_id") for e in entities)
    registered={e["entity_id"]:e for e in entities if isinstance(e.get("entity_id"),str)
                and counts[e["entity_id"]]==1 and e.get("disabled_by") is None}
    by_device={d["id"]:d for d in devices}
    area_names={a["area_id"]:a["name"] for a in areas}
    lux={}
    result={}
    for state in states:
        eid=state.get("entity_id")
        if eid not in registered:continue
        e=registered[eid]
        device_id=e.get("device_id")
        if device_id and is_lux(state):
            lux.setdefault(device_id,[]).append({"entity_id":eid,
                "name":state["attributes"].get("friendly_name") or eid,"state":state.get("state")})
        if not is_presence(state):continue
        dev=by_device.get(device_id,{})
        area=e.get("area_id") or dev.get("area_id")
        result[eid]={"entity_id":eid,"name":state["attributes"].get("friendly_name") or e.get("name") or eid,
                     "area_id":area,"area":area_names.get(area,"Без комнаты"),
                     "device_id":device_id,"integration":e.get("platform"),"state":state.get("state"),
                     "device_class":state["attributes"]["device_class"],"lux_sources":[]}
    for row in result.values():
        row["lux_sources"]=sorted(lux.get(row["device_id"],[]),key=lambda x:x["entity_id"])
    return result

def lux_allows(row,states,now=None):
    if "lux_entity_id" not in row:return True
    state=states.get(row["lux_entity_id"],{})
    if not is_lux(state):return False
    try:
        value=float(state["state"])
        observed=datetime.fromisoformat((state.get("last_reported") or state["last_updated"]).replace("Z","+00:00"))
        age=((now or datetime.now(timezone.utc))-observed).total_seconds()
        return math.isfinite(value) and 0<=value<row["lux_threshold"] and 0<=age<=MAX_LUX_AGE
    except (ValueError,KeyError,TypeError,AttributeError,OverflowError):return False

def mode_blocks(a):
    """Project legacy assignments into identical Day/Night blocks without mutation."""
    if "modes" in a:return a["modes"]
    when=a.get("when","always")
    return {mode:{"enabled":when in ("always",mode),
                  "data":a["night_data"] if mode=="night" and "night_data" in a else a.get("data",{}),
                  **({"off_delay_seconds":a["off_delay_seconds"]} if a.get("off_delay_seconds") is not None else {})}
            for mode in ("day","night")}


def conditional(a):
    if "modes" in a:
        blocks=mode_blocks(a)
        return blocks["day"]!=blocks["night"]
    return a.get("when","always")!="always" or "night_data" in a


def mode_block(a,mode):
    blocks=mode_blocks(a)
    if mode in ("day","night"):return blocks[mode]
    # Preserve mode-independent legacy behavior even without System Globals.
    if "modes" not in a and "night_data" in a:return {"enabled":False,"data":{}}
    if blocks["day"]==blocks["night"]:return blocks["day"]
    return {"enabled":False,"data":{}}


def mode_allows(a,mode):
    return mode_block(a,mode)["enabled"]


def mode_data(a,mode):
    return mode_block(a,mode)["data"]


def mode_delay(a,mode):
    return mode_block(a,mode).get("off_delay_seconds")


def variants(a):
    for block in mode_blocks(a).values():
        if block["enabled"]:
            yield {"entity_id":a["entity_id"],"operation":"on","data":block["data"]}

def commands(row,ids,operation,mode=None):
    result=[]
    for a in row["assignments"]:
        eid=a["entity_id"]
        if eid not in ids:continue
        call={"service":eid.split(".")[0]+".turn_"+operation,"target":{"entity_id":[eid]}}
        if operation=="on":
            if not mode_allows(a,mode):continue
            data=mode_data(a,mode)
            if data:call["data"]=deepcopy(data)
        result.append(call)
    return result
