"""Autonomous System Globals domain core. No HA or MQTT client dependency."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

GLOBAL = "DigitalHouses/Global/night_mode"
PRODUCT = "DigitalHouses/digitalhouses_system_globals_app"
UTC = timezone.utc
PROFILE_FIELDS = (
    "brightness", "color_mode", "color_temp_kelvin", "rgb_color", "volume",
    "display_brightness", "indicator_brightness", "transition_seconds",
    "voice_notifications_enabled", "noncritical_sound_notifications_enabled",
)
CONFIG_FIELDS = ("auto_switch", "night_start", "night_end", "timezone")


class ContractError(ValueError):
    """Invalid command or authoritative state."""


def require(ok, message):
    if not ok:
        raise ContractError(message)


def mapping(value, keys, *, exact=False):
    require(isinstance(value, dict), "Expected object")
    require(set(value) <= set(keys), "Unknown field")
    if exact:
        require(set(value) == set(keys), "Missing field")


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def validate_profile(p):
    mapping(p, PROFILE_FIELDS, exact=True)
    for k in ("brightness", "volume", "display_brightness", "indicator_brightness"):
        require(p[k] is None or integer(p[k], 0, 100), "Invalid " + k)
    for k in ("voice_notifications_enabled", "noncritical_sound_notifications_enabled"):
        require(p[k] is None or type(p[k]) is bool, "Invalid " + k)
    t = p["transition_seconds"]
    require(t is None or (type(t) in (int, float) and 0 <= t <= float("1.7976931348623157e308") and math.isfinite(t)), "Invalid transition_seconds")
    m, k, rgb = p["color_mode"], p["color_temp_kelvin"], p["rgb_color"]
    require(m in (None, "cct", "rgb"), "Invalid color_mode")
    require(k is None or integer(k, 2000, 6000), "Invalid color_temp_kelvin")
    require(rgb is None or (isinstance(rgb, list) and len(rgb) == 3 and all(integer(v, 0, 255) for v in rgb)), "Invalid rgb_color")
    require(
        (m is None and k is None and rgb is None)
        or (m == "cct" and k is not None and rgb is None)
        or (m == "rgb" and k is None and rgb is not None),
        "Color mode requires exactly its corresponding color value",
    )


def update_profile(old, patch):
    mapping(patch, PROFILE_FIELDS)
    require(not (patch.get("color_temp_kelvin") is not None and patch.get("rgb_color") is not None), "Conflicting colors")
    new = deepcopy(old)
    if "color_mode" in patch and patch["color_mode"] != old["color_mode"]:
        new["color_temp_kelvin"] = new["rgb_color"] = None
    new.update(deepcopy(patch))
    validate_profile(new)
    return new


def validate_config(c):
    mapping(c, CONFIG_FIELDS, exact=True)
    a = c["auto_switch"]
    require(a is None or type(a) is bool, "Invalid auto_switch")
    for k in ("night_start", "night_end"):
        v = c[k]
        require(v is None or (isinstance(v, str) and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", v) is not None), "Invalid " + k)
    z = c["timezone"]
    if z is not None:
        require(isinstance(z, str) and bool(z), "Invalid timezone")
        try:
            ZoneInfo(z)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ContractError("Invalid timezone") from e
    if a is True:
        require(all(c[k] is not None for k in CONFIG_FIELDS), "Incomplete schedule")
        require(c["night_start"] != c["night_end"], "Equal schedule boundaries")


def instant(value):
    require(isinstance(value, datetime) and value.utcoffset() is not None, "Timezone-aware datetime required")
    return value.astimezone(UTC)


def decode_instant(value):
    if value is None:
        return None
    require(isinstance(value, str), "Invalid saved timestamp")
    try:
        return instant(datetime.fromisoformat(value))
    except ValueError as e:
        raise ContractError("Invalid saved timestamp") from e


def empty_state():
    return {
        "schema_version": 1, "night_mode": None,
        "config": dict.fromkeys(CONFIG_FIELDS),
        "profiles": {k: dict.fromkeys(PROFILE_FIELDS) for k in ("day", "night")},
        "schedule_cursor": None,
    }


def validate_state(s):
    mapping(s, empty_state(), exact=True)
    require(type(s["schema_version"]) is int and s["schema_version"] == 1, "Unsupported state schema")
    require(s["night_mode"] in (None, "on", "off"), "Invalid night_mode")
    validate_config(s["config"])
    mapping(s["profiles"], ("day", "night"), exact=True)
    for p in s["profiles"].values():
        validate_profile(p)
    cursor = decode_instant(s["schedule_cursor"])
    require(s["config"]["auto_switch"] is not True or cursor is not None, "Missing schedule cursor")


class Store:
    """Atomic JSON persistence. Corrupt data is an error, never reset silently."""
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return empty_state()
        try:
            state = json.loads(raw)
            validate_state(state)
        except (ValueError, TypeError) as e:
            raise ContractError("Invalid persisted state") from e
        return state

    def save(self, state):
        validate_state(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".state-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=False, allow_nan=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            # Persist the directory entry on Linux/HAOS.
            dirfd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        finally:
            if os.path.exists(name):
                os.unlink(name)


@dataclass(frozen=True)
class Publication:
    topic: str
    payload: object
    retain: bool = True
    qos: int = 1

    def wire(self):
        return self.payload if isinstance(self.payload, str) else json.dumps(self.payload, allow_nan=False, separators=(",", ":"))


def latest_boundary(c, now):
    """Most recent local schedule boundary; choose first occurrence at DST fold.
    A nonexistent local time (DST gap) is skipped, not fabricated.
    """
    zone = ZoneInfo(c["timezone"])
    today = now.astimezone(zone).date()
    candidates = []
    for ago in range(3):
        date = today - timedelta(days=ago)
        for key, mode in (("night_start", "on"), ("night_end", "off")):
            h, m = map(int, c[key].split(":"))
            local = datetime(date.year, date.month, date.day, h, m, tzinfo=zone, fold=0)
            when = local.astimezone(UTC)
            if when.astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
                continue
            if when <= now:
                candidates.append((when, mode))
    return max(candidates) if candidates else None


class Engine:
    """Single-owner state machine. Serialize calls in the runtime event loop."""
    def __init__(self, store):
        self.store = store
        self._state = store.load()

    @property
    def state(self):
        return deepcopy(self._state)

    def _commit(self, new):
        self.store.save(new)
        self._state = new

    def snapshot(self):
        s = self._state
        return [
            Publication(GLOBAL + "/state", s["night_mode"] or ""),
            Publication(GLOBAL + "/profiles", deepcopy(s["profiles"])),
            Publication(PRODUCT + "/config/state", deepcopy(s["config"])),
        ]

    def _change_mode(self, new, mode, now):
        previous = new["night_mode"]
        new["night_mode"] = mode
        if new != self._state:
            self._commit(new)
        if previous == mode:
            return []
        out = [Publication(GLOBAL + "/state", mode)]
        if previous is not None:
            zone_name = new["config"]["timezone"]
            observed = now.astimezone(ZoneInfo(zone_name)) if zone_name else now
            out.append(Publication(GLOBAL + "/event", {
                "schema_version": 1, "event_type": "night_mode_" + mode,
                "observed_at": observed.isoformat(),
            }, False))
        return out

    @staticmethod
    def _advance_cursor(new, now):
        old = decode_instant(new["schedule_cursor"])
        new["schedule_cursor"] = max(old, now).isoformat() if old else now.isoformat()

    def command(self, topic, payload, now, *, retained=False):
        require(not retained, "Retained commands are forbidden")
        now = instant(now)
        new = self.state
        if topic == GLOBAL + "/set":
            require(payload in ("on", "off"), "Invalid mode command")
            self._advance_cursor(new, now)
            return self._change_mode(new, payload, now)
        if topic == PRODUCT + "/config/set":
            mapping(payload, CONFIG_FIELDS)
            new["config"].update(deepcopy(payload))
            validate_config(new["config"])
            if new["config"] == self._state["config"]:
                return []
            # A changed schedule applies only future boundaries.
            self._advance_cursor(new, now)
            self._commit(new)
            return [Publication(PRODUCT + "/config/state", deepcopy(new["config"]))]
        if topic == PRODUCT + "/profiles/set":
            mapping(payload, ("day", "night"))
            for key, patch in payload.items():
                new["profiles"][key] = update_profile(new["profiles"][key], patch)
            if new == self._state:
                return []
            self._commit(new)
            return [Publication(GLOBAL + "/profiles", deepcopy(new["profiles"]))]
        raise ContractError("Unknown command topic")

    def import_settings(self, value, now):
        """Atomic import; never import a historical schedule cursor."""
        mapping(value, ("night_mode", "config", "profiles"), exact=True)
        now = instant(now)
        new = self.state
        new.update(deepcopy(value))
        mode = new["night_mode"]
        require(mode in (None, "on", "off"), "Invalid imported mode")
        self._advance_cursor(new, now)
        validate_state(new)
        previous = self._state["night_mode"]
        self._commit(new)
        out = self.snapshot()
        if previous in ("on", "off") and mode in ("on", "off") and previous != mode:
            z = new["config"]["timezone"]
            out.append(Publication(GLOBAL + "/event", {"schema_version":1,
                "event_type":"night_mode_"+mode,
                "observed_at":(now.astimezone(ZoneInfo(z)) if z else now).isoformat()}, False))
        return out

    def tick(self, now):
        now = instant(now)
        new = self.state
        if new["config"]["auto_switch"] is not True:
            return []
        boundary = latest_boundary(new["config"], now)
        cursor = decode_instant(new["schedule_cursor"])
        if boundary is None or boundary[0] <= cursor:
            return []
        new["schedule_cursor"] = boundary[0].isoformat()
        return self._change_mode(new, boundary[1], now)
