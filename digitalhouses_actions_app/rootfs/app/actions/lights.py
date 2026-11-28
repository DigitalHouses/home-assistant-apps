"""Explicit lighting adaptation, independent of Action assignments."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
import re
from zoneinfo import ZoneInfo
from .catalog import CatalogError
from .binding_store import decode_json
from . import profiles

INTERVAL = 1800
MAX_BYTES = 1048576
FIELDS = ("next_rising", "next_noon", "next_setting")


def validate(rows):
    if not isinstance(rows, dict):
        raise CatalogError("Lights must be a mapping")
    result = {}
    for eid, row in rows.items():
        if not isinstance(eid, str) or not re.fullmatch(r"light\.[a-z0-9_]+", eid):
            raise CatalogError("Invalid light entity ID")
        if (not isinstance(row, dict) or set(row) != {"day_night", "adaptive", "color_source"}
                or type(row["day_night"]) is not bool or type(row["adaptive"]) is not bool
                or row["color_source"] not in (None, "cct", "rgb")):
            raise CatalogError("Invalid Lights settings: " + eid)
        if row["adaptive"] and row["color_source"] != "cct":
            raise CatalogError("Adaptive requires CCT: " + eid)
        if row["day_night"] or row["adaptive"]:
            result[eid] = deepcopy(row)
    return result


def read(path):
    if not path.exists():
        return {}
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise CatalogError("Lights settings exceed 1 MiB")
    doc = decode_json(raw)
    if not isinstance(doc, dict) or set(doc) != {"schema", "lights"} or doc["schema"] != 1:
        raise CatalogError("Invalid Lights settings schema")
    return validate(doc["lights"])


def write(path, rows):
    # Validate existing store first; never replace a damaged file silently.
    read(path)
    rows = validate(rows)
    encoded = json.dumps({"schema": 1, "lights": rows}, ensure_ascii=False,
                         allow_nan=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_BYTES:
        raise CatalogError("Lights settings exceed 1 MiB")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(encoded)
            out.flush()
            os.fsync(out.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return rows


def validate_target(eid, row, target):
    if not target or not profiles.supported_light(target):
        raise CatalogError("Light capability unavailable: " + eid)
    ref = {"profile": "current"}
    if row["color_source"] is not None:
        ref["color_source"] = row["color_source"]
    color = profiles.light_color_source(ref, target)
    if color != row["color_source"]:
        raise CatalogError("Select supported color source: " + eid)
    if row["adaptive"] and color != "cct":
        raise CatalogError("Adaptive requires CCT: " + eid)


def overlaps(rows, routes):
    """Reject group/member or alias overlaps, independent of selected functions."""
    def ids(eid):
        route = routes.get(eid)
        if not route:
            return {("ha", eid)}
        base = route["base_topic"]
        if route.get("kind") == "group":
            return {(base, m["ieee"]) for m in route["members"]}
        return {(base, route.get("ieee", route["friendly_name"]))}
    seen = {}
    conflicts = set()
    for eid in sorted(rows):
        for identity in ids(eid):
            if identity in seen:
                conflicts.update((eid, seen[identity]))
            else:
                seen[identity] = eid
    return conflicts


def curve(now, rise, noon, setting):
    if not rise < noon < setting:
        return None
    if now <= rise or now >= setting:
        return 0.
    if now <= noon:
        phase = (now-rise)/(noon-rise)
    else:
        phase = (setting-now)/(setting-noon)
    return (1-math.cos(math.pi*phase))/2


class SolarClock:
    """HA sun events, cached before their next-event attributes roll over.

    HA exposes future events only. On a midday cold start, reconstruct a
    missing elapsed anchor from tomorrow's local wall time until today's
    next-event observations have populated the cache. No geographic settings.
    """
    def __init__(self):
        self.events = {}
        self.zone = None
        self.state = None

    def invalidate(self):
        self.state = None

    def reset(self, zone=None):
        self.invalidate()
        try:
            new_zone = ZoneInfo(zone)
        except (TypeError, ValueError, KeyError):
            new_zone = None
        if new_zone != self.zone:
            self.events.clear()
        self.zone = new_zone

    def observe(self, state, now=None):
        now = now or datetime.now(timezone.utc)
        self.state = None
        if not self.zone or not isinstance(state, dict) or state.get("entity_id") != "sun.sun":
            return
        if state.get("state") not in ("above_horizon", "below_horizon"):
            return
        attrs = state.get("attributes", {})
        parsed = {}
        for field in FIELDS:
            try:
                dt = datetime.fromisoformat(attrs[field].replace("Z", "+00:00"))
                if dt.tzinfo is None or not now-timedelta(minutes=2) <= dt <= now+timedelta(days=2):
                    return
                parsed[field] = dt.astimezone(self.zone)
            except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
                return
        today = now.astimezone(self.zone).date()
        self.events = {k:v for k,v in self.events.items() if k[0] >= today-timedelta(days=1)}
        for field, dt in parsed.items():
            self.events[dt.date(), field] = dt
        self.state = state["state"]

    def factor(self, now=None):
        now = now or datetime.now(timezone.utc)
        if self.state is None or self.zone is None:
            return None
        today = now.astimezone(self.zone).date()
        if self.state == "below_horizon":
            return 0.
        anchors = []
        for field in FIELDS:
            dt = self.events.get((today, field))
            if dt is None:
                future = self.events.get((today+timedelta(days=1), field))
                if future is None:
                    return None
                dt = future-timedelta(days=1)
            anchors.append(dt.astimezone(timezone.utc))
        return curve(now, *anchors)


def adaptive_parameters(target, snapshot, factor):
    if factor is None or not target.get("cct") or not snapshot:
        return None
    day = snapshot.get("day", {}).get("color_temp_kelvin")
    night = snapshot.get("night", {}).get("color_temp_kelvin")
    if type(day) is not int or type(night) is not int:
        return None
    lo, hi = target.get("min_kelvin"), target.get("max_kelvin")
    if type(lo) is not int or type(hi) is not int or not 0 < lo <= hi:
        return None
    value = round(night + min(1., max(0., factor))*(day-night))
    return {"color_temp_kelvin": max(lo, min(hi, value))}
