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
        obj = get("/states/" + entity)
        return HAResult(state, isinstance(obj, dict) and obj.get("state") == nonce, True)
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        return HAResult(None, False, False)
