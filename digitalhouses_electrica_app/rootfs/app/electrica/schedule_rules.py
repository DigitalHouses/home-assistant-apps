"""Named daily point schedules. HA is the only timezone/solar authority."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from .catalog import CatalogError
from .light_rules import parse_rule

KINDS={"time","sunrise","sunset"}
SOLAR_FIELDS={"sunrise":"next_rising","sunset":"next_setting"}

def is_schedule(eid):
    return isinstance(eid,str) and re.fullmatch(r"schedule\.[a-z0-9_]{1,64}",eid) is not None

def validate_row(row):
    if not isinstance(row,dict) or set(row)!={"entity_id","name","enabled","trigger","assignments"} or not is_schedule(row["entity_id"]):
        raise CatalogError("Invalid schedule row")
    if not isinstance(row["name"],str) or not row["name"].strip() or len(row["name"])>100 or type(row["enabled"]) is not bool:
        raise CatalogError("Invalid schedule name or enabled")
    trigger=row["trigger"]
    if not isinstance(trigger,dict) or trigger.get("kind") not in KINDS:
        raise CatalogError("Invalid schedule trigger")
    kind=trigger["kind"]
    if kind=="time":
        if set(trigger)!={"kind","time"} or not isinstance(trigger["time"],str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]",trigger["time"]):
            raise CatalogError("Time requires HH:MM")
    elif set(trigger)!={"kind","offset_minutes"} or type(trigger["offset_minutes"]) is not int or not -720<=trigger["offset_minutes"]<=720:
        raise CatalogError("Solar offset requires integer minutes from -720 to 720")
    if not isinstance(row["assignments"],list) or len(row["assignments"])>16 or (row["enabled"] and not row["assignments"]):
        raise CatalogError("Schedule requires 1..16 assignments when enabled")
    if row["assignments"]:
        parsed=parse_rule({"assignments":row["assignments"]})
        # Daily events express explicit desired actions, not toggles or timer chains.
        if parsed.get("target_timers") or any(a["operation"] in ("toggle","play_pause","next","previous") or "brightness_step_pct" in a.get("data",{}) for a in row["assignments"]):
            raise CatalogError("Schedule requires explicit operation without toggle, relative step or Auto-OFF")
    return deepcopy(row)

def clock_occurrences(trigger,zone,start,end):
    """Return UTC instants for local dates. First fold only; skip nonexistent time."""
    h,m=map(int,trigger["time"].split(":"))
    date=start.astimezone(zone).date()-timedelta(days=1)
    last=end.astimezone(zone).date()+timedelta(days=1)
    # Callers bound the scan window; never iterate arbitrarily after clock jumps.
    if (last-date).days>5:return []
    result=[]
    while date<=last:
        local=datetime(date.year,date.month,date.day,h,m,tzinfo=zone,fold=0)
        utc=local.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None)==local.replace(tzinfo=None):
            result.append((date.isoformat(),utc))
        date+=timedelta(days=1)
    return result

def solar_times(state,now):
    if not isinstance(state,dict) or state.get("entity_id")!="sun.sun" or state.get("state") not in ("above_horizon","below_horizon"):
        return {}
    attrs=state.get("attributes",{})
    result={}
    for kind,field in SOLAR_FIELDS.items():
        try:
            dt=datetime.fromisoformat(attrs[field].replace("Z","+00:00"))
            if dt.tzinfo is not None and now-timedelta(minutes=1)<=dt<=now+timedelta(days=370):
                result[kind]=dt.astimezone(timezone.utc)
        except (ValueError,TypeError,KeyError,AttributeError,OverflowError):pass
    return result

def commands(row):
    from .control import light_commands
    rule=parse_rule({"assignments":row["assignments"]})
    return light_commands({"bindings":{"schedule":rule},"fingerprint":{"actions":["schedule"]}},"schedule")
