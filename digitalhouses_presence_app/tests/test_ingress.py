"""Single-install Supervisor Ingress security and identity unit tests."""
import ipaddress
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from dh_presence.ui import (
    CORE_NETWORK, SUPERVISOR_INGRESS, authenticated_ingress_user,
    gps_candidates, ingress_context,
)


class IngressTests(unittest.TestCase):
    def headers(self, **kw):
        hdrs = {
            "X-Remote-User-Id": "the-authenticated-user",
            "X-Remote-User-Display-Name": "Жилец",
            "X-Forwarded-Host": "192.168.11.33",
            "X-Forwarded-For": "192.168.11.54, 172.30.32.1",
        }
        hdrs.update(kw)
        return hdrs

    def test_valid_authenticated_local_user_ip(self):
        context = ingress_context(SUPERVISOR_INGRESS, self.headers())
        self.assertEqual(context, {
            "user_id": "the-authenticated-user",
            "user_name": "Жилец",
            "ip": "192.168.11.54",
        })

    def test_rejects_proxy_or_spoofed_xff_prefix(self):
        # Any extra forwarded hop is inconsistent with direct local Core
        # access, even if its second-last peer resembles a private LAN phone.
        headers = self.headers(**{
            "X-Forwarded-For": "192.168.11.199, 192.168.11.54, 172.30.32.1",
        })
        with self.assertRaises(PermissionError):
            ingress_context(SUPERVISOR_INGRESS, headers)

    def test_rejects_non_supervisor_peer(self):
        with self.assertRaises(PermissionError):
            ingress_context("192.168.11.5", self.headers())

    def test_rejects_missing_auth_header(self):
        hdrs = self.headers()
        hdrs.pop("X-Remote-User-Id")
        with self.assertRaises(PermissionError):
            ingress_context(SUPERVISOR_INGRESS, hdrs)

    def test_remote_authenticated_user_can_view_but_not_register(self):
        headers = self.headers(**{
            "X-Forwarded-Host": "myhouse.digitalhouses.vip",
            "X-Forwarded-For": "10.0.1.20, 172.30.32.1",
        })
        self.assertEqual(
            authenticated_ingress_user(SUPERVISOR_INGRESS, headers)["user_name"],
            "Жилец")
        with self.assertRaises(PermissionError):
            ingress_context(SUPERVISOR_INGRESS, headers)

    def test_rejects_cloudflare_external_host(self):
        headers = self.headers(**{
            "X-Forwarded-Host": "myhouse.digitalhouses.vip",
        })
        with self.assertRaises(PermissionError):
            ingress_context(SUPERVISOR_INGRESS, headers)

    def test_rejects_vpn_cgnat_remote_core_peer(self):
        for peer in ("8.8.8.8", "100.100.100.100", "127.0.0.1", "::1"):
            with self.subTest(peer=peer):
                hdrs = self.headers(**{
                    "X-Forwarded-For": f"{peer}, 172.30.32.1",
                })
                with self.assertRaises(PermissionError):
                    ingress_context(SUPERVISOR_INGRESS, hdrs)

    def test_rejects_impossible_proxy_chain(self):
        for value in ("192.168.11.54", "bad-ip, 172.30.32.1",
                      "192.168.11.54, 10.99.99.99"):
            with self.subTest(chain=value):
                with self.assertRaises(PermissionError):
                    ingress_context(SUPERVISOR_INGRESS, self.headers(
                        **{"X-Forwarded-For": value}))

    def test_supervisor_ingress_ip_matches_documented_endpoint(self):
        self.assertEqual(SUPERVISOR_INGRESS, "172.30.32.2")
        self.assertIn(ipaddress.ip_address("172.30.32.1"), CORE_NETWORK)

    def test_ingress_url_without_trailing_slash_still_uses_correct_api_path(self):
        from dh_presence.ui import HTML
        self.assertIn("if(!path.endsWith('/'))path+='/'", HTML)
        self.assertIn("fetch(APP_ROOT+url", HTML)

    def test_gps_candidates_only_observations_and_no_user_guessing(self):
        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        source = [
            {"entity_id": "device_tracker.13promax_sky",
             "state": "home", "attributes": {"source_type": "gps",
                                              "friendly_name": "13ProMAX .SKY"}},
            {"entity_id": "device_tracker.router",
             "state": "home", "attributes": {"source_type": "router"}},
            {"entity_id": "sensor.foo", "attributes": {"source_type": "gps"}},
        ]
        with patch("dh_presence.ui.urlopen", return_value=FakeResponse()):
            with patch("dh_presence.ui.json.load", return_value=source):
                out = gps_candidates("test_token")
        self.assertEqual(out, [{
            "tracker": "device_tracker.13promax_sky",
            "device_name": "13ProMAX .SKY",
        }])


if __name__ == "__main__":
    unittest.main()
