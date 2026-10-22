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

    def fetch(self) -> tuple[list, list, list]:
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
            for ident, command in enumerate((
                "config/device_registry/list", "config/area_registry/list",
                "config/entity_registry/list",
            ), 1):
                ws.send(json.dumps({"id": ident, "type": command}))
                answer = json.loads(ws.recv())
                if (answer.get("id") != ident or answer.get("type") != "result"
                        or answer.get("success") is not True
                        or not isinstance(answer.get("result"), list)):
                    raise CatalogError("HA Registry call failed: " + command)
                result.append(answer["result"])
            return result[0], result[1], result[2]
        finally:
            ws.close()
