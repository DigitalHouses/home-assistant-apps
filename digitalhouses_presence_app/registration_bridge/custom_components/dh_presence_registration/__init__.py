"""Minimal authenticated HA Core WebSocket adapter for DH Presence.

This bridge never scans a network and never guesses a mobile device from a user.
The Home Assistant App verifies a fresh ARP reply separately before enrollment.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ipaddress
import secrets

from aiohttp import web
import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

DOMAIN = "dh_presence_registration"
STORE_KEY = DOMAIN + ".pending"
TTL = timedelta(minutes=5)
HISTORY_TTL = timedelta(hours=24)


def now_utc():
    return datetime.now(timezone.utc)


def parse_time(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def is_local_candidate(remote: str | None) -> bool:
    """Reject remote, proxy-class, loopback, link-local and VPN CGNAT peers.

    The App must subsequently establish direct on-link reachability using ARP.
    A private address on its own is never sufficient proof of registration.
    """
    try:
        ip = ipaddress.ip_address(remote)
    except (TypeError, ValueError):
        return False
    return (isinstance(ip, ipaddress.IPv4Address)
            and ip.is_private and not ip.is_loopback and not ip.is_link_local
            and not ip.is_multicast and not ip.is_unspecified
            and ip not in ipaddress.ip_network("100.64.0.0/10"))


def companion_candidates(hass, user_id):
    """Only a user's own registered Mobile Companion GPS entities."""
    registry = er.async_get(hass)
    result = []
    for entry in hass.config_entries.async_entries("mobile_app"):
        if entry.data.get("user_id") != user_id:
            continue
        trackers = []
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
            if entity.domain != "device_tracker" or entity.disabled_by:
                continue
            state = hass.states.get(entity.entity_id)
            if (state is not None and state.attributes.get("source_type") == "gps"):
                trackers.append(entity.entity_id)
        for tracker in trackers:
            result.append({
                "entry_id": entry.entry_id,
                "device_id": entry.data.get("device_id"),
                "device_name": entry.data.get("device_name", "Mobile Companion"),
                "tracker": tracker,
            })
    return result


class PendingView(HomeAssistantView):
    url = "/api/dh_presence/registration/pending"
    name = "api:dh_presence:registration_pending"
    requires_auth = True

    async def get(self, request):
        # Supervisor Core API token must be a privileged internal session.
        # Ordinary resident users cannot read other people's IPs/registrations.
        user = request["hass_user"]
        if not user.is_admin:
            return web.json_response({"error": "admin_required"}, status=403)
        items = request.app["hass"].data[DOMAIN]["requests"].values()
        now = now_utc()
        pending = [dict(item) for item in items
                   if item.get("status") == "pending"
                   and now - parse_time(item.get("created_at")) < TTL]
        return web.json_response({"requests": pending})


class AckView(HomeAssistantView):
    url = "/api/dh_presence/registration/ack"
    name = "api:dh_presence:registration_ack"
    requires_auth = True

    async def post(self, request):
        if not request["hass_user"].is_admin:
            return web.json_response({"error": "admin_required"}, status=403)
        try:
            data = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        rid, mac = data.get("request_id"), data.get("mac")
        state = request.app["hass"].data[DOMAIN]
        entry = state["requests"].get(rid)
        if not entry or entry["status"] != "pending" or now_utc() - parse_time(entry["created_at"]) >= TTL:
            return web.json_response({"error": "request_expired"}, status=409)
        try:
            raw_mac = str(mac).lower()
            parts = raw_mac.split(":")
            assert len(parts) == 6 and all(len(p) == 2 and int(p, 16) >= 0 for p in parts)
            assert raw_mac not in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff")
        except (ValueError, AssertionError):
            return web.json_response({"error": "invalid_mac"}, status=400)
        entry["status"] = "registered"
        entry["mac"] = raw_mac
        entry["registered_at"] = now_utc().isoformat()
        await state["store"].async_save({"requests": list(state["requests"].values())})
        return web.json_response({"success": True})


@websocket_api.websocket_command({vol.Required("type"): "dh_presence/candidates"})
@callback
def ws_candidates(hass, connection, msg):
    connection.send_result(msg["id"], companion_candidates(hass, connection.user.id))


@websocket_api.websocket_command({
    vol.Required("type"): "dh_presence/register",
    vol.Required("entry_id"): str,
    vol.Required("tracker"): str,
})
@websocket_api.async_response
async def ws_register(hass, connection, msg):
    remote = connection.remote
    if not is_local_candidate(remote):
        connection.send_error(msg["id"], "not_allowed",
                              "Connect directly over local Wi-Fi, not via Cloudflare/VPN/proxy")
        return
    matches = [item for item in companion_candidates(hass, connection.user.id)
               if item["entry_id"] == msg["entry_id"] and item["tracker"] == msg["tracker"]]
    if len(matches) != 1:
        connection.send_error(msg["id"], "not_allowed",
                              "Selected Mobile Companion GPS tracker does not belong to this HA user")
        return
    state = hass.data[DOMAIN]
    async with state["lock"]:
        now = now_utc()
        # Idempotent re-registration for a resident; no silent second device
        # inferred from the user account. Explicit choice required each time.
        requests = state["requests"]
        requests = {key: value for key, value in requests.items()
                    if now - parse_time(value.get("created_at")) < HISTORY_TTL}
        if len(requests) >= 100:
            connection.send_error(msg["id"], "not_allowed", "Registration queue is full")
            return
        chosen = matches[0]
        record = {
            "request_id": secrets.token_urlsafe(18),
            "status": "pending",
            "created_at": now.isoformat(),
            "user_id": connection.user.id,
            "user_name": (connection.user.name or "").strip() or "HA user",
            "device_name": chosen["device_name"],
            "device_id": chosen["device_id"],
            "entry_id": chosen["entry_id"],
            "tracker": chosen["tracker"],
            "ip": remote,
        }
        requests[record["request_id"]] = record
        await state["store"].async_save({"requests": list(requests.values())})
        state["requests"] = requests
    # No proof of an actual phone MAC yet. The App must perform active ARP
    # from the local L2 network and persist only after that observation.
    connection.send_result(msg["id"], {
        "request_id": record["request_id"],
        "status": "pending_arp_verification",
        "user_name": record["user_name"],
        "device_name": record["device_name"],
        "tracker": record["tracker"],
    })


@websocket_api.websocket_command({vol.Required("type"): "dh_presence/registration_status"})
@callback
def ws_status(hass, connection, msg):
    records = [item for item in hass.data[DOMAIN]["requests"].values()
               if item.get("user_id") == connection.user.id]
    connection.send_result(msg["id"], [
        {"request_id": item["request_id"], "status": item["status"],
         "tracker": item["tracker"], "device_name": item["device_name"],
         "ip": item.get("ip"), "mac": item.get("mac")}
        for item in sorted(records, key=lambda r: r["created_at"], reverse=True)[:10]
    ])


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    import asyncio
    store = Store(hass, 1, STORE_KEY)
    data = await store.async_load() or {"requests": []}
    records = {r["request_id"]: r for r in data.get("requests", [])
               if isinstance(r, dict) and isinstance(r.get("request_id"), str)
               and now_utc() - parse_time(r.get("created_at")) < HISTORY_TTL}
    hass.data[DOMAIN] = {"requests": records, "store": store, "lock": asyncio.Lock()}
    websocket_api.async_register_command(hass, ws_candidates)
    websocket_api.async_register_command(hass, ws_register)
    websocket_api.async_register_command(hass, ws_status)
    hass.http.register_view(PendingView())
    hass.http.register_view(AckView())
    return True
