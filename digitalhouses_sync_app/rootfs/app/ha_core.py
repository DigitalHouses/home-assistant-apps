"""Home Assistant Core API through the Supervisor proxy (no personal HA token).

Requires homeassistant_api: true. Token remains inside the App process.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from sync_engine import SyncError


class CoreAPI:
    def __init__(self, *, token: str | None = None, host: str = "http://supervisor"):
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        if not self.token:
            raise SyncError("SUPERVISOR_TOKEN is not available")
        if host != "http://supervisor":
            raise SyncError("Only Supervisor's local Core API proxy is supported")
        self.host = host

    def _rest(self, path: str, *, post: bool = False):
        req = urllib.request.Request(
            self.host + "/core/api/" + path,
            data=b"{}" if post else None,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
            method="POST" if post else "GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                if response.status != 200:
                    raise SyncError("HA API returned HTTP " + str(response.status))
                return json.loads(response.read(2_000_000))
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as exc:
            raise SyncError("Home Assistant Core REST API unavailable") from exc

    def versions(self) -> dict[str, str]:
        results = {}
        for entity in ("sensor.dh_pve_agent_version", "sensor.dh_plex_agent_version"):
            try:
                value = self._rest("states/" + urllib.parse.quote(entity, safe=""))
            except SyncError:
                results[entity] = "unavailable"
                continue
            if not isinstance(value, dict) or value.get("entity_id") != entity:
                raise SyncError("HA API returned unexpected version sensor")
            state = value.get("state")
            results[entity] = state if isinstance(state, str) else "unavailable"
        return results

    def check_config(self) -> bool:
        value = self._rest("config/core/check_config", post=True)
        return isinstance(value, dict) and value.get("result") == "valid"

    def dashboard(self) -> dict:
        try:
            import websocket
        except ImportError as exc:
            raise SyncError("websocket-client missing from App image") from exc
        try:
            sock = websocket.create_connection(
                "ws://supervisor/core/websocket", timeout=15, enable_multithread=True,
            )
            try:
                hello = json.loads(sock.recv())
                if hello.get("type") != "auth_required":
                    raise SyncError("HA WebSocket authentication handshake failed")
                sock.send(json.dumps({"type": "auth", "access_token": self.token}))
                authenticated = json.loads(sock.recv())
                if authenticated.get("type") != "auth_ok":
                    raise SyncError("Supervisor API not authorized by Home Assistant")
                sock.send(json.dumps({
                    "id": 1, "type": "lovelace/config", "force": True,
                    "url_path": "digital-houses",
                }))
                for _ in range(8):
                    response = json.loads(sock.recv())
                    if response.get("id") != 1:
                        continue
                    if response.get("type") != "result" or not response.get("success"):
                        raise SyncError("DigitalHouses YAML dashboard is not registered")
                    value = response.get("result")
                    if not isinstance(value, dict):
                        raise SyncError("HA returned an invalid dashboard configuration")
                    return value
                raise SyncError("No Lovelace response received")
            finally:
                sock.close()
        except (ValueError, OSError, TimeoutError, websocket.WebSocketException) as exc:
            if isinstance(exc, SyncError):
                raise
            raise SyncError("Home Assistant WebSocket is unavailable") from exc
