"""Named reusable explicit command sets; IDs are app-owned, not HA entities."""
import re
from copy import deepcopy
from .catalog import CatalogError

def is_common(eid):
    return isinstance(eid,str) and re.fullmatch(r"common_action\.[a-z0-9_]{1,64}",eid) is not None

def validate_row(row):
    from .light_rules import parse_rule
    if not isinstance(row,dict) or set(row)!={"entity_id","name","enabled","assignments"} or not is_common(row["entity_id"]):
        raise CatalogError("Invalid common action")
    if type(row["enabled"]) is not bool or not isinstance(row["name"],str) or not row["name"].strip() or len(row["name"])>100:
        raise CatalogError("Invalid common action name or enabled")
    assignments=row["assignments"]
    if not isinstance(assignments,list) or len(assignments)>16 or (row["enabled"] and not assignments):
        raise CatalogError("Common action requires 1..16 targets when enabled")
    if assignments:
        parsed=parse_rule({"assignments":assignments})
        if parsed.get("target_timers") or any(is_common(a["entity_id"]) or a["operation"] in ("toggle","play_pause","next","previous") or "brightness_step_pct" in a.get("data",{}) for a in assignments):
            raise CatalogError("Common action requires explicit operations; no nesting or timers")
    return deepcopy(row)

def reference(commands):
    if len(commands)==1 and commands[0]["service"]=="common_action.run":
        return commands[0]["target"]["entity_id"][0]
    return None

def commands(row):
    from .schedule_rules import commands
    return commands(row)
