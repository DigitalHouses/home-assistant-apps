"""Unit-test the HA Core bridge's pure policy without installing HA Core.

The actual HA WebSocket HTTP endpoints require live HAOS integration testing.
"""
import ast
import ipaddress
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "registration_bridge/custom_components/dh_presence_registration/__init__.py"


def load_pure(name, **names):
    source = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    found = [f for f in source.body if isinstance(f, ast.FunctionDef) and f.name == name]
    assert len(found) == 1
    found[0].decorator_list = []
    ns = dict(names)
    exec(compile(ast.fix_missing_locations(ast.Module(body=found, type_ignores=[])),
                 str(BRIDGE), "exec"), ns)
    return ns[name]


class RegistrationBridgeContractTests(unittest.TestCase):
    def test_core_bridge_source_compiles(self):
        compile(BRIDGE.read_text(encoding="utf-8"), str(BRIDGE), "exec")

    def test_local_candidate_rejects_remote_vpn_and_unknown(self):
        candidate = load_pure("is_local_candidate", ipaddress=ipaddress)
        self.assertTrue(candidate("192.168.11.54"))
        for ip in (None, "", "8.8.8.8", "127.0.0.1",
                   "100.100.100.100", "169.254.0.1", "::1"):
            with self.subTest(ip=ip):
                self.assertFalse(candidate(ip))

    def test_candidates_are_bound_to_authenticated_ha_user(self):
        phone = SimpleNamespace(entry_id="phone", data={
            "user_id": "self", "device_id": "phone-id",
            "device_name": "13ProMAX .SKY",
        })
        tablet = SimpleNamespace(entry_id="tablet", data={
            "user_id": "self", "device_id": "tablet-id",
            "device_name": "Home iPad",
        })
        other = SimpleNamespace(entry_id="other", data={
            "user_id": "other-user", "device_id": "other-id",
            "device_name": "Other user phone",
        })
        candidates = load_pure("companion_candidates", er=SimpleNamespace(
            async_get=lambda hass: None,
            async_entries_for_config_entry=lambda registry, key: [
                SimpleNamespace(entity_id="device_tracker." + key,
                                domain="device_tracker", disabled_by=None)
            ],
        ))
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_entries=lambda domain: [phone, tablet, other]),
            states=SimpleNamespace(get=lambda eid: SimpleNamespace(
                attributes={"source_type": "gps"},
            )),
        )
        result = candidates(hass, "self")
        self.assertEqual({item["entry_id"] for item in result}, {"phone", "tablet"})
        self.assertEqual({item["device_name"] for item in result},
                         {"13ProMAX .SKY", "Home iPad"})
        self.assertNotIn("other-user", str(result))

    def test_server_only_trusted_identity_from_websocket(self):
        text = BRIDGE.read_text(encoding="utf-8")
        for required in (
            "connection.user.id",
            "connection.user.name",
            "remote = connection.remote",
            'msg["entry_id"]',
            'msg["tracker"]',
            "is_local_candidate(remote)",
            "companion_candidates(hass, connection.user.id)",
            'item.get("status") == "pending"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)
        self.assertNotIn('msg["user_id"]', text)
        self.assertNotIn('msg["ip"]', text)
        self.assertNotIn('msg["mac"]', text)


if __name__ == "__main__":
    unittest.main()
