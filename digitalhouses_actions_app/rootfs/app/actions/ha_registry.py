"""Aqara IEEE -> optional existing HA device/switch entity lookup."""
from __future__ import annotations
import json
from collections.abc import Mapping
from .catalog import CatalogError


def _matched_devices(devices: object, ieees: set[str]) -> dict:
    if not isinstance(devices, list):
        raise CatalogError("Invalid HA Device Registry")
    found = {ieee: [] for ieee in ieees}
    for dev in devices:
        if not isinstance(dev, Mapping):
            raise CatalogError("Invalid HA Device Registry entry")
        ids, connections = dev.get("identifiers", []), dev.get("connections", [])
        if not isinstance(ids, list) or not isinstance(connections, list):
            raise CatalogError("Invalid HA identity fields")
        matched = set()
        for item in ids + connections:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            domain, value = item
            if not isinstance(domain, str) or not isinstance(value, str):
                continue
            if domain in ("zigbee", "zha", "mqtt"):
                v = value.lower()
                for ieee in ieees:
                    if v == ieee or v == "zigbee2mqtt_" + ieee:
                        matched.add(ieee)
        for ieee in matched:
            found[ieee].append(dev)
    return found


def device_names(devices: object, ieees: set[str]) -> dict:
    """Human-readable HA device names; never infer from individual relays."""
    result = {}
    for ieee, owners in _matched_devices(devices, ieees).items():
        if len(owners) != 1:
            continue
        for key in ("name_by_user", "name"):
            value = owners[0].get(key)
            if isinstance(value, str) and value.strip():
                result[ieee] = value.strip()
                break
    return result


def areas_from_registries(devices: object, areas: object, ieees: set[str]) -> dict:
    if not isinstance(areas, list):
        raise CatalogError("Invalid HA Area Registry")
    names = {}
    for area in areas:
        if not isinstance(area, Mapping) or not isinstance(area.get("area_id"), str):
            raise CatalogError("Invalid HA Area Registry entry")
        names[area["area_id"]] = area.get("name")
    owners = _matched_devices(devices, ieees)
    result = {}
    for ieee, devs in owners.items():
        if len(devs) > 1:
            raise CatalogError("Ambiguous HA Device Registry identity for " + ieee)
        if not devs:
            result[ieee] = None
            continue
        area_id = devs[0].get("area_id")
        if area_id is None:
            result[ieee] = None
        elif area_id not in names or not isinstance(names[area_id], str):
            raise CatalogError("Invalid HA area for " + ieee)
        else:
            result[ieee] = {"area_id": area_id, "name": names[area_id]}
    return result


def switch_entities(devices: object, entities: object, ieees: set[str]) -> tuple[dict, dict]:
    """Return an unambiguous HA switch.* when present, otherwise a reason.

    Missing switch.* is normal for battery remotes, so the Scan caller may
    allocate a logical-only key while still binding hardware strictly.
    """
    owners = _matched_devices(devices, ieees)
    if not isinstance(entities, list):
        raise CatalogError("Invalid HA Entity Registry")
    by_id = {}
    for entity in entities:
        if not isinstance(entity, Mapping):
            raise CatalogError("Invalid HA Entity Registry entry")
        device_id, entity_id = entity.get("device_id"), entity.get("entity_id")
        if isinstance(device_id, str) and isinstance(entity_id, str) and entity_id.startswith("switch."):
            if entity.get("disabled_by") is None:
                by_id.setdefault(device_id, set()).add(entity_id)
    resolved, errors = {}, {}
    for ieee, devs in owners.items():
        if len(devs) != 1 or not isinstance(devs[0].get("id"), str):
            errors[ieee] = "HA device is missing or ambiguous"
            continue
        choices = sorted(by_id.get(devs[0]["id"], set()))
        if len(choices) == 1:
            resolved[ieee] = choices[0]
        else:
            errors[ieee] = ("No existing switch.* entity" if not choices
                            else "Multiple switch.* entities: " + ", ".join(choices))
    return resolved, errors


class HARegistryClient:
    def __init__(self, token: str, url: str = "ws://supervisor/core/websocket",
                 timeout: float = 8):
        if not token:
            raise CatalogError("SUPERVISOR_TOKEN is missing")
        self.token, self.url, self.timeout = token, url, timeout

    def _fetch(self, commands: tuple) -> list:
        """Authenticate each read-only HA registry session; never perform writes."""
        import websocket
        ws = websocket.create_connection(self.url, timeout=self.timeout,
                                         http_proxy_host=None)
        try:
            welcome = json.loads(ws.recv())
            if welcome.get("type") != "auth_required":
                raise CatalogError("HA WebSocket did not request authentication")
            ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            authorized = json.loads(ws.recv())
            if authorized.get("type") != "auth_ok":
                raise CatalogError("HA WebSocket authorization failed")
            result = []
            for ident, command in enumerate(commands, 1):
                request={"type":command} if isinstance(command,str) else command
                ws.send(json.dumps({**request,"id":ident}))
                answer = json.loads(ws.recv())
                if (answer.get("id") != ident or answer.get("type") != "result"
                        or answer.get("success") is not True
                        or not isinstance(answer.get("result"), list if isinstance(command,str) else dict)):
                    raise CatalogError("HA Registry call failed: " + request["type"])
                result.append(answer["result"])
            return result
        finally:
            ws.close()

    def fetch(self) -> tuple[list, list, list]:
        devices, areas, entities = self._fetch((
            "config/device_registry/list", "config/area_registry/list",
            "config/entity_registry/list"))
        return devices, areas, entities

    def fetch_entities(self) -> list:
        """Read HA entity registry for native-light transport classification."""
        return self._fetch(("config/entity_registry/list",))[0]

    def fetch_states(self) -> list:
        return self._fetch(("get_states",))[0]

    def fetch_timezone(self) -> str:
        """Read authoritative HA timezone from the Core config endpoint."""
        import urllib.request
        req = urllib.request.Request("http://supervisor/core/api/config",
                                     headers={"Authorization":"Bearer "+self.token})
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            return json.load(response)["time_zone"]

    def fetch_temperature_unit(self) -> str:
        import urllib.request
        req=urllib.request.Request("http://supervisor/core/api/config",
                                   headers={"Authorization":"Bearer "+self.token})
        with urllib.request.urlopen(req,timeout=self.timeout) as response:
            return json.load(response)["unit_system"]["temperature"]

    def browse_media(self, entity_id, ref=None):
        from .media_rules import media_ref, browse_result
        import re
        if not isinstance(entity_id,str) or not re.fullmatch(r"media_player\.[a-z0-9_]+",entity_id):
            raise CatalogError("Invalid media player")
        request={"type":"media_player/browse_media","entity_id":entity_id}
        if ref is not None:
            request.update(media_ref(ref))
        return browse_result(self._fetch((request,))[0])

    def watch_states(self, stop, baseline, changed):
        """Read-only HA subscription; reconnect establishes a silent baseline."""
        import time
        import websocket
        ws = websocket.create_connection(self.url, timeout=self.timeout,
                                         http_proxy_host=None)
        try:
            if json.loads(ws.recv()).get("type") != "auth_required":
                raise CatalogError("HA WebSocket authentication unavailable")
            ws.send(json.dumps({"type":"auth","access_token":self.token}))
            if json.loads(ws.recv()).get("type") != "auth_ok":
                raise CatalogError("HA WebSocket authorization failed")
            ws.send(json.dumps({"id":1,"type":"subscribe_events","event_type":"state_changed"}))
            ack = json.loads(ws.recv())
            if ack.get("id") != 1 or ack.get("success") is not True:
                raise CatalogError("HA state subscription failed")
            ws.send(json.dumps({"id":2,"type":"get_states"}))
            # Events before this result are represented by the baseline.
            while not stop.is_set():
                reply = json.loads(ws.recv())
                if reply.get("id") == 2 and reply.get("type") == "result":
                    if reply.get("success") is not True or not isinstance(reply.get("result"),list):
                        raise CatalogError("HA baseline unavailable")
                    baseline(reply["result"])
                    break
            ws.settimeout(1)
            next_ping = time.monotonic()+15
            ping_deadline = None
            while not stop.is_set():
                now = time.monotonic()
                if ping_deadline is not None and now >= ping_deadline:
                    raise CatalogError("HA state subscription heartbeat lost")
                if now >= next_ping and ping_deadline is None:
                    ws.send(json.dumps({"id":3,"type":"ping"}))
                    ping_deadline = now+8
                    next_ping = now+15
                try:
                    reply = json.loads(ws.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                if reply.get("id")==3 and reply.get("type")=="pong":
                    ping_deadline = None
                elif reply.get("id")==1 and reply.get("type")=="event":
                    event = reply.get("event",{}).get("data",{})
                    if isinstance(event.get("entity_id"),str):
                        changed(event["entity_id"],event.get("new_state"))
        finally:
            ws.close()
