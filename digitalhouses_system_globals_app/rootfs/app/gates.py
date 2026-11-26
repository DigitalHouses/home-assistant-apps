"""Readiness is fresh, positive evidence, not elapsed startup time."""
from dataclasses import dataclass
import json
import urllib.request
import urllib.error

GATE_KEYS = ("mqtt_ready", "ha_ready", "zigbee_ready")


class Gates:
    def __init__(self, *, require_ha, require_z2m, ttl):
        self.required = {"mqtt_ready"}
        if require_ha:
            self.required.add("ha_ready")
        if require_z2m:
            self.required.add("zigbee_ready")
        self.ttl = ttl
        self.reset()

    def reset(self):
        self.evidence = {}
        self.reasons = dict.fromkeys(GATE_KEYS, "awaiting_probe")

    def prove(self, key, now):
        self.evidence[key] = now
        self.reasons[key] = "ready"

    def invalidate(self, key, reason):
        self.evidence.pop(key, None)
        self.reasons[key] = reason

    def states(self, now):
        result = {k: k in self.evidence and 0 <= now-self.evidence[k] < self.ttl
                  for k in GATE_KEYS}
        result["system_ready"] = all(result[k] for k in self.required)
        return result

    def diagnostics(self, now):
        values = self.states(now)
        return {k: {"ready": values[k], "required": k in self.required,
                    "reason": "probe_expired" if k in self.evidence and not values[k] else self.reasons[k]}
                for k in GATE_KEYS}


class Z2MProbe:
    def __init__(self):
        self.online = False
        self.info = False
        self.devices = False
        self.transaction = None

    def begin(self, nonce):
        self.transaction = nonce

    def observe(self, topic, value):
        if topic == "state":
            online = (value == "online" or isinstance(value, dict) and value.get("state") == "online")
            if not online:
                self.__init__()
                return False
            self.online = True
        elif topic == "info":
            self.info = isinstance(value, dict) and isinstance(value.get("version"), str) and bool(value["version"])
            if not self.info:
                return False
        elif topic == "devices":
            self.devices = isinstance(value, list) and all(
                isinstance(x, dict) and isinstance(x.get("ieee_address"), str) for x in value)
            if not self.devices:
                return False
        elif topic == "response/health_check":
            if self.transaction is None or not isinstance(value, dict) or value.get("transaction") != self.transaction:
                return None
            self.transaction = None
            data = value.get("data")
            return bool(self.online and self.info and self.devices and value.get("status") == "ok"
                        and isinstance(data, dict) and data.get("healthy") is True)
        return None


BRIDGE_FIELDS = ("state", "info", "devices", "response/health_check")


def bridge_topic(topic):
    """MQTT cannot match arbitrary-depth suffixes; filter the broker stream."""
    for field in BRIDGE_FIELDS:
        suffix = "/bridge/" + field
        if topic.endswith(suffix):
            base = topic[:-len(suffix)]
            if base and not base.startswith("$"):
                return base, field
    return None


class Z2MRegistry:
    """Discover all bridge namespaces and track fresh evidence independently."""
    def __init__(self, ttl, timeout):
        self.ttl = ttl
        self.timeout = timeout
        self.bridges = {}
        self.evidence = {}
        self.deadlines = {}
        self.metadata = {}

    def observe(self, topic, raw, retained, now):
        matched = bridge_topic(topic)
        if matched is None:
            return False
        base, field = matched
        if field == "response/health_check":
            z = self.bridges.get(base)
            if z is None or retained or now > self.deadlines.get(base, -1):
                return True
            try:
                value = json.loads(raw)
            except ValueError:
                return True
            result = z.observe(field, value)
            if result is True:
                self.evidence[base] = now
            elif result is False:
                self.evidence.pop(base, None)
            return True
        if raw == "":
            # Explicit retained tombstones retire a namespace only after all
            # three discovery records have been cleared.
            if retained and base in self.bridges:
                self.metadata[base].discard(field)
                self.evidence.pop(base, None)
                setattr(self.bridges[base], "online" if field == "state" else field, False)
                if not self.metadata[base]:
                    self.bridges.pop(base)
                    self.deadlines.pop(base, None)
                    self.metadata.pop(base)
            return True
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        valid = (
            (field == "state" and (value in ("online", "offline") if isinstance(value, str)
                                   else isinstance(value, dict) and value.get("state") in ("online", "offline")))
            or (field == "info" and isinstance(value, dict) and isinstance(value.get("version"), str) and bool(value["version"]))
            or (field == "devices" and isinstance(value, list) and all(
                isinstance(x, dict) and isinstance(x.get("ieee_address"), str) for x in value))
        )
        if base not in self.bridges and not valid:
            return True
        z = self.bridges.setdefault(base, Z2MProbe())
        self.metadata.setdefault(base, set()).add(field)
        result = z.observe(field, value)
        if result is False:
            self.evidence.pop(base, None)
        return True

    def requests(self, now, nonce_fn):
        for base, z in self.bridges.items():
            if z.transaction is not None and now > self.deadlines.get(base, -1):
                z.transaction = None
                self.evidence.pop(base, None)
            if z.online and z.transaction is None:
                nonce = nonce_fn()
                z.begin(nonce)
                self.deadlines[base] = now + self.timeout
                yield base + "/bridge/request/health_check", nonce

    def update_gate(self, gates, now):
        if not self.bridges:
            gates.invalidate("zigbee_ready", "no_bridges_discovered")
        elif not all(base in self.evidence and 0 <= now-self.evidence[base] < self.ttl
                     for base in self.bridges):
            gates.invalidate("zigbee_ready", "bridge_not_ready")
        else:
            # Freshness is bounded by the oldest bridge, never the newest.
            gates.prove("zigbee_ready", min(self.evidence[base] for base in self.bridges))

    def diagnostics(self, now):
        return {base: {"online": z.online, "info": z.info, "devices": z.devices,
                       "ready": base in self.evidence and 0 <= now-self.evidence[base] < self.ttl}
                for base, z in sorted(self.bridges.items())}


@dataclass(frozen=True)
class HAResult:
    state: str | None
    nonce_seen: bool
    reachable: bool


def ha_probe(base, token, nonce, entity):
    """Only read HA API; do not write device state or call services."""
    if not base or not token:
        return HAResult(None, False, False)
    def get(path):
        request = urllib.request.Request(base.rstrip("/") + path,
                                         headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.load(response)
    try:
        cfg = get("/config")
        state = cfg.get("state") if isinstance(cfg, dict) else None
        if state != "RUNNING":
            return HAResult(state, False, True)
        try:
            obj = get("/states/" + entity)
        except (OSError, ValueError, TypeError):
            return HAResult(state, False, True)
        return HAResult(state, isinstance(obj, dict) and obj.get("state") == nonce, True)
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        return HAResult(None, False, False)
