"""Authoritative HA administrator verification for private Presence diagnostics.

Supervisor Ingress sends an authenticated HA user ID, but deliberately does
NOT supply an is_admin flag. Query HA Core's authenticated WebSocket user list
with the App's existing Supervisor token; fail closed if unauthorized.

The admin check runs on the backend for EVERY private diagnostic request.
A Lovelace CSS condition alone would be cosmetic, not access control.
"""
from __future__ import annotations

import json
from typing import Any


class AdministratorVerificationUnavailable(RuntimeError):
    """HA Core could not prove whether the caller is an administrator."""


def is_authorized_ha_admin(user_id: str, token: str) -> bool:
    """Return True only for an active HA admin; no name/role guessing.

    Never trust client JavaScript, request query parameters or caller-supplied
    role headers. HA's 'config/auth/list' WebSocket command requires admin
    privileges itself. Any denial/outage here must never expose the registry.
    """
    if not isinstance(user_id, str) or not user_id.strip() or not token:
        return False

    try:
        from websockets.sync.client import connect

        with connect("ws://supervisor/core/websocket",
                     open_timeout=5, close_timeout=2) as ws:
            initial = json.loads(ws.recv(timeout=5))
            if initial.get("type") != "auth_required":
                raise AdministratorVerificationUnavailable("No HA auth challenge")
            ws.send(json.dumps({"type": "auth", "access_token": token}))
            response = json.loads(ws.recv(timeout=5))
            if response.get("type") != "auth_ok":
                raise AdministratorVerificationUnavailable("HA Core WS authorization denied")
            ws.send(json.dumps({"id": 1, "type": "config/auth/list"}))
            result = json.loads(ws.recv(timeout=5))
    except Exception as exc:
        # Fail closed for any WebSocket transport, timeout or protocol error.
        # Only an explicit, valid admin role result may unlock diagnostics.
        raise AdministratorVerificationUnavailable("Unable to verify HA admin status") from exc

    if (not isinstance(result, dict) or result.get("type") != "result"
            or result.get("id") != 1 or result.get("success") is not True
            or not isinstance(result.get("result"), list)):
        raise AdministratorVerificationUnavailable("HA admin list denied or invalid")

    matches: list[dict[str, Any]] = [
        item for item in result["result"]
        if isinstance(item, dict) and item.get("id") == user_id
    ]
    if len(matches) != 1:
        return False
    item = matches[0]
    groups = item.get("group_ids")
    return bool(
        item.get("is_active") is True
        and item.get("system_generated") is not True
        and isinstance(groups, list)
        and "system-admin" in groups
    )
