"""Home Assistant Device/Area registry via authenticated Supervisor WS proxy.

No fuzzy friendly-name based area lookup. No fake room on untrusted matches.
"""
from __future__ import annotations
import json
from collections.abc import Mapping

from .catalog import CatalogError


def areas_from_registries(
    devices: object, areas: object, ieee_addresses: set[str]
) -> dict[str, dict | None]:
    """Return HA Area per IEEE; raise for duplicate/conflicting HA identities."""
    if not isinstance(devices, list) or not isinstance(areas, list):
        raise CatalogError("HA device and area registry results must be lists")
    area_names = {}
    for area in areas:
        if not isinstance(area, Mapping) or not isinstance(area.get("area_id"), str) or not isinstance(area.get("name"), str):
            raise CatalogError("Invalid Home Assistant Area Registry entry")
        area_names[area["area_id"]] = area["name"]
    owners = {ieee: [] for ieee in ieee_addresses}
    for device in devices:
        if not isinstance(device, Mapping):
            raise CatalogError("Invalid Home Assistant Device Registry entry")
        candidates = device.get("identifiers", [])
        connections = device.get("connections", [])
        if not isinstance(candidates, list) or not isinstance(connections, list):
            raise CatalogError("Invalid HA device identifiers/connections")
        matched = set()
        for pair in candidates + connections:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            domain, value = pair
            if not isinstance(domain, str) or not isinstance(value, str):
                continue
            identity = value.lower()
            # Z2M MQTT device registry identifiers may be "zigbee2mqtt_0x<16hex>"
            # or a Zigbee connection may store the plain IEEE.
            if domain in ("mqtt", "zigbee", "zha"):
                for ieee in owners:
                    if identity == ieee or identity == "zigbee2mqtt_" + ieee:
                        matched.add(ieee)
        for ieee in matched:
            owners[ieee].append(device)
    found = {}
    for ieee, devices_for_ieee in owners.items():
        if not devices_for_ieee:
            found[ieee] = None
            continue
        if len(devices_for_ieee) != 1:
            raise CatalogError(f"Ambiguous HA Device Registry identity for {ieee}")
        device = devices_for_ieee[0]
        area_id = device.get("area_id")
        if area_id is None:
            found[ieee] = None
            continue
        if not isinstance(area_id, str) or area_id not in area_names:
            raise CatalogError(f"Invalid HA area for {ieee}: {area_id}")
        found[ieee] = {"area_id": area_id, "name": area_names[area_id]}
    return found


class HARegistryClient:
    """Synchronous bounded registry snapshot; imported lazily for unit tests."""
    def __init__(self, token: str, url: str = "ws://supervisor/core/websocket",
                 timeout: float = 8):
        if not token:
            raise CatalogError("SUPERVISOR_TOKEN is missing")
        self.token, self.url, self.timeout = token, url, timeout

    def fetch(self) -> tuple[list, list]:
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
            for ident, command in enumerate(
                ("config/device_registry/list", "config/area_registry/list"), 1
            ):
                ws.send(json.dumps({"id": ident, "type": command}))
                answer = json.loads(ws.recv())
                if (answer.get("id") != ident or answer.get("type") != "result"
                        or answer.get("success") is not True):
                    raise CatalogError(f"HA Registry call failed: {command}")
                if not isinstance(answer.get("result"), list):
                    raise CatalogError(f"Invalid HA Registry response: {command}")
                result.append(answer["result"])
            return result[0], result[1]
        finally:
            ws.close()
