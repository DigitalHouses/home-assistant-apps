"""Admin-only DH Presence debug contracts: no private data to residents."""
import json
import sys
import unittest
from types import ModuleType
from unittest.mock import patch
from dh_presence.admin import is_authorized_ha_admin, AdministratorVerificationUnavailable
from dh_presence.ui import handler_factory, admin_registration_diagnostics


class Socket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def recv(self, timeout):
        return json.dumps(next(self.messages))
    def send(self, data):
        self.sent.append(json.loads(data))


def check(user_id="admin", is_admin=True, allowed=True):
    users = [
        {"id": "admin", "is_active": True, "system_generated": False,
         "group_ids": ["system-admin"] if is_admin else ["system-users"]},
        {"id": "resident", "is_active": True,
         "group_ids": ["system-users"]},
    ]
    ws = Socket([
        {"type": "auth_required"},
        {"type": "auth_ok"},
        {"id": 1, "type": "result", "success": allowed, "result": users},
    ])
    module, sync, client = ModuleType("websockets"), ModuleType("websockets.sync"), ModuleType("websockets.sync.client")
    module.sync, sync.client, client.connect = sync, client, lambda url, **kw: ws
    with patch.dict(sys.modules, {"websockets": module, "websockets.sync": sync,
                                  "websockets.sync.client": client}):
        value = is_authorized_ha_admin(user_id, "supervisor-token")
    return value, ws


class AdminTests(unittest.TestCase):
    def test_authority_is_ha_admin_id_not_display_name(self):
        authorized, ws = check()
        self.assertTrue(authorized)
        self.assertEqual(ws.sent[1], {"id": 1, "type": "config/auth/list"})
        self.assertFalse(check("resident")[0])
        self.assertFalse(check("admin", is_admin=False)[0])
        self.assertFalse(check("unknown")[0])

    def test_failure_never_authorizes(self):
        self.assertFalse(is_authorized_ha_admin("", "token"))
        self.assertFalse(is_authorized_ha_admin("admin", ""))
        with self.assertRaises(AdministratorVerificationUnavailable):
            check(allowed=False)

    def get_request(self, path, uid="resident"):
        cls = handler_factory("token", "/data/registry.json", set())
        req = object.__new__(cls)
        req.path, req.client_address = path, ("172.30.32.2", 5555)
        req.headers = {"X-Remote-User-Id": uid, "X-Remote-User-Display-Name": "Resident"}
        responses = []
        req.reply = lambda status, payload: responses.append((status, payload))
        return req, responses

    def test_non_admin_private_endpoint_cannot_read_registry(self):
        req, replies = self.get_request("/api/admin/debug")
        with patch("dh_presence.ui.is_authorized_ha_admin", return_value=False):
            with patch("dh_presence.ui.admin_registration_diagnostics") as read:
                req.do_GET()
                read.assert_not_called()
        self.assertEqual(replies, [(403, {"error": "admin_required"})])

    def test_admin_endpoint_returns_private_debug_data(self):
        req, replies = self.get_request("/api/admin/debug", "admin")
        with patch("dh_presence.ui.is_authorized_ha_admin", return_value=True):
            with patch("dh_presence.ui.admin_registration_diagnostics",
                       return_value=[{"ip": "192.168.11.54", "mac": "88:b9:45:80:a7:55"}]):
                req.do_GET()
        self.assertEqual(replies[0][0], 200)
        self.assertEqual(replies[0][1]["residents"][0]["ip"], "192.168.11.54")

    def test_core_admin_unavailable_fails_closed(self):
        req, replies = self.get_request("/api/admin/debug", "admin")
        with patch("dh_presence.ui.is_authorized_ha_admin",
                   side_effect=AdministratorVerificationUnavailable("down")):
            with patch("dh_presence.ui.admin_registration_diagnostics") as read:
                req.do_GET()
                read.assert_not_called()
        self.assertEqual(replies[0][0], 503)

    def test_normal_status_never_exposes_address_data(self):
        req, replies = self.get_request("/api/status")
        records = [{"user_id": "resident", "user_name": "Resident",
                    "device_name": "Phone", "tracker": "device_tracker.phone",
                    "ip": "192.168.11.54", "mac": "88:b9:45:80:a7:55"}]
        with patch("dh_presence.ui.load_registry", return_value=records):
            req.do_GET()
        result = json.dumps(replies[0][1])
        self.assertNotIn("192.168.11.54", result)
        self.assertNotIn("88:b9:45:80:a7:55", result)

    def test_debug_addresses_are_registration_snapshots(self):
        registry = [{"user_name": "Resident", "device_name": "Phone",
                     "tracker": "device_tracker.phone",
                     "ip": "192.168.11.54", "mac": "88:b9:45:80:a7:55"}]
        states = [{"entity_id": "device_tracker.phone", "state": "home",
                   "attributes": {}, "last_reported": "2026-10-14T19:29:26+00:00"}]
        with patch("dh_presence.ui.load_registry", return_value=registry):
            with patch("dh_presence.ui.read_core_states", return_value=states):
                rec = admin_registration_diagnostics("token", "path")[0]
        self.assertEqual(rec["gps"], "home")
        self.assertEqual(rec["wifi"], "unavailable")
        self.assertIn("при регистрации", rec["ip_mac_note"])
