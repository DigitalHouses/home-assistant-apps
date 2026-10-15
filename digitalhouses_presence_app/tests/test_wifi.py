"""Native Wi-Fi positive evidence only. A silent iPhone is not away."""
import unittest
from datetime import datetime, timedelta, timezone

from dh_presence.core import Engine, Mode, Status
from dh_presence.wifi import WifiEvidence, poll_registered_wifi, probe_registered_phone

T0 = datetime(2026, 10, 15, 7, 0, tzinfo=timezone.utc)
LINK = {"user_id": "ha-user", "user_name": "Resident",
        "device_name": "iPhone", "tracker": "device_tracker.phone",
        "ip": "192.168.11.54", "mac": "88:b9:45:80:a7:55"}


def engine(mode=Mode.GPS, last="home"):
    e = Engine(mode=mode, wifi_absence_minutes=15, freshness_seconds=300)
    e.add("device_tracker.phone", "iPhone", {"confirmed": last}, user_name="Resident")
    return e


class WifiEvidenceTests(unittest.TestCase):
    def test_matching_mac_returns_trusted_home(self):
        probe = lambda ip: ("88:B9:45:80:A7:55", "enp6s18")
        self.assertEqual(
            probe_registered_phone(LINK, probe),
            WifiEvidence(True, "mac_verified", "enp6s18"))

    def test_mismatch_ip_reassignment_is_not_a_new_resident(self):
        self.assertEqual(probe_registered_phone(
            LINK, lambda ip: ("02:aa:bb:cc:dd:ee", "enp6s18")),
            WifiEvidence(False, "mac_mismatch"))

    def test_sleeping_iphone_and_network_error_are_not_away(self):
        for error in (RuntimeError("No reply"), TimeoutError(),
                      OSError("Network down"), ValueError("Not on link")):
            def fail(_ip):
                raise error
            with self.subTest(error=type(error).__name__):
                self.assertEqual(
                    probe_registered_phone(LINK, fail),
                    WifiEvidence(False, "no_verified_reply"))

    def test_registered_phone_only_no_router_or_nmap(self):
        e = engine()
        e.add("device_tracker.other", "Unknown")
        called = []
        def probe(record):
            called.append(record["tracker"])
            return WifiEvidence(True, "mac_verified", "enp6s18")
        events = poll_registered_wifi(e, [LINK], T0, probe)
        self.assertEqual(called, ["device_tracker.phone"])
        self.assertEqual(e.residents[LINK["tracker"]].wifi, Status.HOME)
        self.assertEqual(e.residents["device_tracker.other"].wifi, Status.UNAVAILABLE)
        self.assertFalse(any(x["event_type"] == "wifi_out" for x in events))

    def test_missing_reply_for_15_minutes_is_never_verified_departure(self):
        e = engine(Mode.HYBRID)
        poll_registered_wifi(e, [LINK], T0,
                             lambda record: WifiEvidence(True, "mac_verified", "enp6s18"))
        events = []
        for minute in range(1, 17):
            events += poll_registered_wifi(
                e, [LINK], T0 + timedelta(minutes=minute),
                lambda record: WifiEvidence(False, "no_verified_reply"))
            e.expire(T0 + timedelta(minutes=minute))
        self.assertEqual(e.residents[LINK["tracker"]].wifi, Status.UNAVAILABLE)
        self.assertEqual(e.residents[LINK["tracker"]].confirmed, Status.HOME)
        self.assertFalse(any(ev["event_type"] in ("wifi_out", "departure") for ev in events))
        self.assertEqual(e.residents[LINK["tracker"]].wifi_probe_result, "no_verified_reply")

    def test_wifi_only_mode_uses_fresh_evidence_not_retained_gps(self):
        e = engine(Mode.WIFI, "home")
        self.assertEqual(e.snapshot()["status"], "unavailable")
        poll_registered_wifi(e, [LINK], T0,
                             lambda record: WifiEvidence(True, "mac_verified", "enp6s18"))
        self.assertEqual(e.snapshot()["status"], "home")
        self.assertEqual(e.snapshot()["residents_home"], 1)
        e.expire(T0 + timedelta(minutes=6))
        self.assertEqual(e.snapshot()["status"], "home")
        e.expire(T0 + timedelta(minutes=16))
        self.assertEqual(e.snapshot()["status"], "unavailable")
        self.assertEqual(e.snapshot()["residents_home"], 0)

    def test_stale_gps_away_does_not_cancel_fresh_hybrid_wifi_home(self):
        e = engine(Mode.HYBRID, "not_home")
        e.gps_observation(LINK["tracker"], Status.NOT_HOME, T0-timedelta(days=1))
        poll_registered_wifi(e, [LINK], T0,
                             lambda record: WifiEvidence(True, "mac_verified", "enp6s18"))
        self.assertEqual(e.residents[LINK["tracker"]].confirmed, Status.HOME)
        e.gps_observation(LINK["tracker"], Status.NOT_HOME, T0-timedelta(days=1),
                          decision_at=T0+timedelta(minutes=1))
        self.assertEqual(e.residents[LINK["tracker"]].confirmed, Status.HOME)

    def test_wrong_mac_invalidates_wifi_home_without_claiming_away(self):
        e = engine(Mode.WIFI)
        poll_registered_wifi(e, [LINK], T0,
                             lambda record: WifiEvidence(True, "mac_verified", "enp6s18"))
        events = poll_registered_wifi(e, [LINK], T0+timedelta(minutes=1),
                                      lambda record: WifiEvidence(False, "mac_mismatch"))
        self.assertEqual(e.snapshot()["status"], "unavailable")
        self.assertEqual(e.residents[LINK["tracker"]].wifi_probe_result, "mac_mismatch")
        self.assertFalse(events)

    def test_snapshot_contains_no_ip_or_mac(self):
        e = engine(Mode.GPS)
        poll_registered_wifi(e, [LINK], T0,
                             lambda record: WifiEvidence(True, "mac_verified", "enp6s18"))
        snapshot = str(e.snapshot())
        self.assertNotIn(LINK["ip"], snapshot)
        self.assertNotIn(LINK["mac"], snapshot)
        self.assertIn("wifi_last_verified_at", snapshot)


if __name__ == "__main__":
    unittest.main()
