"""Single-install Supervisor Ingress security and identity unit tests."""
import ipaddress
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from dh_presence.ui import (
    CORE_NETWORK, SUPERVISOR_INGRESS, authenticated_ingress_user,
    find_router_wifi_tracker, gps_candidates, ingress_context,
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

    def test_ingress_server_listens_only_on_internal_host_bridge(self):
        from dh_presence.ui import start_ingress_ui
        with patch("dh_presence.ui.ThreadingHTTPServer") as server_cls:
            with patch("dh_presence.ui.Thread") as thread_cls:
                server_cls.return_value = SimpleNamespace(
                    serve_forever=lambda: None,
                )
                start_ingress_ui("fake", "/tmp/presence-test-registry", [])
                self.assertEqual(server_cls.call_args.args[0], ("172.30.32.1", 8099))
                thread_cls.return_value.start.assert_called_once()

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


    def test_router_wifi_tracker_match_by_registered_mac(self):
        states = [
            {"entity_id": "device_tracker.13promax_sky",
             "state": "home", "attributes": {
                 "source_type": "gps", "mac_address": "88:B9:45:80:A7:55"}},
            {"entity_id": "device_tracker.not_a_phone",
             "state": "home", "attributes": {
                 "source_type": "router", "network_type": "LAN",
                 "mac_address": "88:B9:45:80:A7:55"}},
            {"entity_id": "device_tracker.13promax_sky_2",
             "state": "home", "attributes": {
                 "source_type": "router", "network_type": "WLAN",
                 "mac_address": "88:B9:45:80:A7:55", "ip_address": "192.168.11.54"}},
        ]
        self.assertEqual(
            find_router_wifi_tracker(states, "88:b9:45:80:a7:55"),
            {"status": "matched", "tracker": "device_tracker.13promax_sky_2",
             "state": "home"})
        self.assertEqual(find_router_wifi_tracker(states, "8a:43:3e:74:09:83"),
                         {"status": "not_found"})

    def test_router_tracker_absent_and_ambiguous_matches(self):
        away = {"entity_id": "device_tracker.iphone", "state": "not_home",
                "attributes": {"source_type": "router",
                               "mac_address": "8A:43:3E:74:09:83"}}
        self.assertEqual(find_router_wifi_tracker([away], "8a:43:3e:74:09:83"),
                         {"status": "matched", "tracker": "device_tracker.iphone",
                          "state": "not_home"})
        duplicate = {"entity_id": "device_tracker.iphone_2",
                     "state": "unknown", "attributes": {
                         "source_type": "router", "mac": "8a:43:3e:74:09:83"}}
        self.assertEqual(
            find_router_wifi_tracker([away, duplicate], "8a:43:3e:74:09:83"),
            {"status": "multiple", "count": 2})

    def test_wifi_lookup_runs_on_explicit_select_and_not_on_initial_load(self):
        from dh_presence.ui import HTML
        self.assertIn("q('tracker').addEventListener('change',lookupWifiTracker)", HTML)
        self.assertIn("api('api/lookup-wifi'", HTML)
        self.assertIn("'X-Presence-Request':'lookup-wifi'", HTML)
        self.assertIn("placeholder.value=''", HTML)


if __name__ == "__main__":
    unittest.main()
